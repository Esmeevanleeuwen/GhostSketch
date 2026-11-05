"""Govern feed contract -> persisted notebook page, including repeat imports."""
import copy
import tempfile
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from ghostsketch.app import create_app
from ghostsketch.govern import GovernSource

RID, SID = str(uuid4()), str(uuid4())
TOKEN = 'test-key-' * 5
RECORDING = dict(id=RID, filename='Brainstorm.m4a', sha256='a'*64, duration_ms=6000, status='ready')
TRANSCRIPT = dict(**RECORDING, segments=[dict(id=SID, sequence=0, start_ms=0, end_ms=6000,
    text='Misschien kunnen we een prototype maken. We moeten morgen samen testen.')])


def source(data=None, status=200):
    def handle(request):
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        value = (data or TRANSCRIPT) if 'id' in request.url.params else {'recordings':[RECORDING]}
        return httpx.Response(status,json={'ok':True,'data':value})
    return GovernSource('http://127.0.0.1:8080/dictation-feed.php', TOKEN, httpx.MockTransport(handle))


def test_import_preserves_edits_sources_and_ink_on_repeat():
    with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory,govern=source()),base_url='http://localhost:8000') as client:
        token = client.get('/api/bootstrap').json()['token']
        headers = {'X-GhostSketch-Token':token}
        project = client.post('/api/projects',headers=headers,json={'title':'Notitieboek'}).json()
        assert client.get('/api/govern/recordings').json()['recordings'][0]['id'] == RID
        path = f'/api/projects/{project["id"]}/govern/{RID}'
        first = client.post(path,headers=headers)
        assert first.status_code == 200,first.text
        first = first.json()
        project = first['project']
        page = project['sessions'][0]
        assert page['source'] == 'govern' and page['cards']
        assert page['segments'][0]['govern_source']['segment_id'] == SID
        page['page_text'] = 'Mijn eigen aanvulling'
        page['section'] = 'Uitvindingen'
        page['strokes'] = [{'id':'stroke-one','points':[{'x':1,'y':2},{'x':3,'y':4}]}]
        page['cards'][0].update(title='Mijn betere titel',user_edited=True,status='accepted')
        saved = client.put(f'/api/projects/{project["id"]}',headers=headers,json={'expected_revision':project['revision'],'project':project})
        assert saved.status_code == 200,saved.text
        again = client.post(path,headers=headers).json()['project']
        assert len(again['sessions']) == 1
        again_page = again['sessions'][0]
        assert len(again_page['segments']) == 1
        assert len(again_page['cards']) == len(page['cards'])
        assert again_page['cards'][0]['title'] == 'Mijn betere titel'
        assert again_page['page_text'] == 'Mijn eigen aanvulling'
        assert again_page['strokes'] == page['strokes']
        # Full snapshot exports/imports preserve notebook additions.
        exported = client.post('/api/projects/import',headers=headers,json=again)
        assert exported.status_code == 200,exported.text
        assert exported.json()['sessions'][0]['strokes'][0]['id'] != 'stroke-one'
        imported_id = exported.json()['id']
        repeat_export = client.post(f'/api/projects/{imported_id}/govern/{RID}', headers=headers)
        assert repeat_export.status_code == 200, repeat_export.text
        assert len(repeat_export.json()['project']['sessions'][0]['segments']) == 1
        # A linked original cannot be rewritten through the snapshot editor.
        again['sessions'][0]['segments'][0]['text'] = 'Anders'
        changed = client.put(f'/api/projects/{again["id"]}',headers=headers,json={'expected_revision':again['revision'],'project':again})
        assert changed.status_code == 422


@pytest.mark.parametrize('change',[{'status':'pending'}, {'id':str(uuid4())}, {'duration_ms':5000}, {'segments':[]}])
def test_reject_incomplete_or_wrong_source(change):
    transcript = copy.deepcopy(TRANSCRIPT)
    transcript.update(change)
    with pytest.raises(Exception):
        source(transcript).read(RID)


def test_local_configuration_and_authentication_failure():
    for url in ['https://example.org/dictation-feed.php','http://localhost:8080/other','http://localhost:8080/dictation-feed.php?token=secret']:
        with pytest.raises(ValueError):
            GovernSource(url,TOKEN)
    assert not GovernSource('','').configured
    with pytest.raises(Exception):
        source(status=401).read()


def test_ink_limit_and_missing_token():
    with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory,govern=source()),base_url='http://localhost:8000') as client:
        assert client.post(f'/api/projects/unknown/govern/{RID}').status_code == 403

@pytest.fixture
def capture():
    from storage_fixture import StorageFixture
    from test_api import FakeAdapters
    from ghostsketch.models import now_iso
    storage, adapters = StorageFixture(), FakeAdapters()
    with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory, adapters, govern=storage.source),base_url='http://localhost:8000') as client:
        bootstrap = client.get('/api/bootstrap').json()
        assert bootstrap['capabilities']['govern_storage'] is True
        assert storage.source.token not in str(bootstrap)
        headers={'X-GhostSketch-Token':bootstrap['token']}
        project=client.post('/api/projects',headers=headers,json={'title':'Gesprek'}).json()
        project['sessions']=[dict(id='capture-page',title='Opname',source='microphone',created_at=now_iso())]
        project=client.put('/api/projects/'+project['id'],headers=headers,json={'expected_revision':project['revision'],'project':project}).json()
        def upload(request_id='capture-one',start_ms=0):
            return client.post('/api/sessions/capture-page/audio',headers=headers,data={'request_id':request_id,'start_ms':start_ms},files={'file':('spraak.wav',b'synthetic audio','audio/wav')})
        yield client,headers,project,storage,adapters,upload


def test_capture_archives_before_transcribing_and_links_exact_source(capture):
    client,headers,project,storage,adapters,upload=capture
    original_transcribe=adapters.transcribe
    def transcribe(content,filename):
        assert list(storage.bytes.values()) == [content]
        assert next(iter(storage.rows.values()))['status']=='pending'
        return original_transcribe(content,filename)
    adapters.transcribe=transcribe
    first=upload()
    assert first.status_code==200,first.text
    segment=first.json()['project']['sessions'][0]['segments'][0]
    rid=segment['govern_source']['recording_id']; row=storage.rows[rid]
    assert row['status']=='ready' and row['segments'][0]['text']==segment['text']
    assert row['segments'][0]['id']==segment['govern_source']['segment_id']
    assert adapters.audio_calls==1
    repeat=upload('retry-after-uncertain-response')
    assert repeat.status_code==200 and len(repeat.json()['project']['sessions'][0]['segments'])==1
    assert adapters.audio_calls==1 and len(storage.rows)==1
    assert upload(start_ms=8000).status_code==409


def test_archive_failure_stops_before_transcription(capture):
    client,headers,project,storage,adapters,upload=capture
    storage.fail_upload=True
    assert upload().status_code==503
    assert adapters.audio_calls==0 and not storage.rows
    assert client.get('/api/projects/'+project['id']).json()==project


@pytest.mark.parametrize('failure',['transcribe','complete'])
def test_failed_processing_retains_archive_and_resumes_from_ghostsketch(capture,failure):
    client,headers,project,storage,adapters,upload=capture
    adapters.failure=failure=='transcribe'
    storage.fail_complete=failure=='complete'
    failed=upload()
    assert failed.status_code==503 and 'De opname staat in Govern' in failed.text
    assert client.get('/api/projects/'+project['id']).json()==project
    row=next(iter(storage.rows.values()))
    assert row['status']=='pending' and storage.bytes[row['id']]==b'synthetic audio'
    adapters.failure=False; storage.fail_complete=False
    path=f'/api/projects/{project["id"]}/govern/{row["id"]}'
    resumed=client.post(path,headers=headers)
    assert resumed.status_code==200,resumed.text
    page=next(p for p in resumed.json()['project']['sessions'] if p['source']=='govern')
    assert page['cards'] and len(page['segments'])==1
    assert storage.rows[row['id']]['status']=='ready' and 'audio' in storage.calls
    again=client.post(path,headers=headers).json()
    assert len(again['project']['sessions'])==2
    assert len(next(p for p in again['project']['sessions'] if p['source']=='govern')['segments'])==1


def test_audio_requires_writable_govern_before_model(capture):
    client,headers,project,storage,adapters,upload=capture
    storage.source.url='http://127.0.0.1:8080/dictation-feed.php'
    assert client.get('/api/bootstrap').json()['capabilities']['govern_storage'] is False
    assert upload().status_code==503
    assert adapters.audio_calls==0 and storage.calls==[]


def test_retry_rejects_changed_archived_audio(capture):
    client,headers,project,storage,adapters,upload=capture
    adapters.failure=True
    assert upload().status_code==503
    row=next(iter(storage.rows.values()));storage.bytes[row['id']]=b'changed'
    adapters.failure=False
    resumed=client.post(f'/api/projects/{project["id"]}/govern/{row["id"]}',headers=headers)
    assert resumed.status_code==503 and 'gewijzigd' in resumed.text
    assert adapters.audio_calls==1
    assert client.get('/api/projects/'+project['id']).json()==project
