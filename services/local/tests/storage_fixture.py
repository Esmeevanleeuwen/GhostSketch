"""Synthetic Govern HTTP boundary, retaining bytes and transcripts across requests."""
from email import message_from_bytes
from email.policy import default
import hashlib
from uuid import uuid4
import httpx
from ghostsketch.govern import GovernSource

class StorageFixture:
    def __init__(self):
        self.rows={}; self.bytes={}; self.calls=[]; self.fail_upload=False; self.fail_complete=False
        self.source=GovernSource('http://127.0.0.1:8080/ghostsketch-storage.php','test-storage-key-'*3,httpx.MockTransport(self.handle))

    def handle(self,request):
        action=request.url.params.get('action')
        self.calls.append(action)
        assert request.headers['authorization']=='Bearer '+'test-storage-key-'*3
        if action=='upload':
            if self.fail_upload:return httpx.Response(503,json={'ok':False})
            message=message_from_bytes(('Content-Type: '+request.headers['content-type']+'\r\n\r\n').encode()+request.read(),policy=default)
            part=next(p for p in message.iter_parts() if p.get_param('name',header='content-disposition')=='file')
            audio=part.get_payload(decode=True); sha=hashlib.sha256(audio).hexdigest()
            row=next((r for r in self.rows.values() if r['sha256']==sha),None)
            if not row:
                rid=str(uuid4());row=dict(id=rid,filename=part.get_filename(),sha256=sha,duration_ms=8000,status='pending',segments=[])
                self.rows[rid]=row;self.bytes[rid]=audio
            data=row
        elif action=='list': data={'recordings':list(self.rows.values())}
        elif action=='audio':return httpx.Response(200,content=self.bytes[request.url.params['id']])
        elif action=='recording':data=self.rows[request.url.params['id']]
        elif action=='complete':
            if self.fail_complete:return httpx.Response(503,json={'ok':False})
            import json
            payload=json.loads(request.read());data=self.rows[payload['id']]
            assert data['sha256']==payload['sha256']
            if data['status']=='pending':
                data['segments']=[dict(id=str(uuid4()),sequence=0,start_ms=0,end_ms=8000,text=payload['text'],provider='ghostsketch-whisper')]
                data['status']='ready'
            else:assert data['segments'][0]['text']==payload['text']
        else:raise AssertionError(action)
        return httpx.Response(200,json={'ok':True,'data':data})
