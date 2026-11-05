import unittest
from copy import deepcopy

from ghostsketch.organizer import extract_rules


class TestRuleOrganizer(unittest.TestCase):
    def test_mixed_brainstorm_preserves_intents_and_exact_source_words(self):
        text = (
            "Wat als we onze tools op een externe SSD zetten? "
            "Kan Unity vanaf die SSD werken? "
            "Laten we eerst een lokale server bouwen. "
            "We besluiten de eerste proef op één computer te doen."
        )
        cards = extract_rules(text, "segment-1")
        self.assertEqual([c["type"] for c in cards], ["idea", "question", "action", "decision"])
        self.assertTrue(all(c["text"] in text for c in cards))
        self.assertTrue(all(c["source_segment_ids"] == ["segment-1"] for c in cards))
        self.assertIn("SSD", cards[0]["text"])
        self.assertIn("Unity", cards[1]["text"])

    def test_possibilities_never_become_decisions(self):
        for text in (
            "Misschien kunnen we voor Linux kiezen.",
            "Wat als we voor Linux besluiten?",
            "We zouden voor Linux kunnen kiezen.",
            "We besluiten misschien om Linux te gebruiken.",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_rules(text, "s1")[0]["type"], "idea")

    def test_explicit_decisions_are_recognised_as_proposals(self):
        for text in (
            "We hebben afgesproken om eerst lokaal te starten.",
            "Afgesproken: de eerste versie blijft stil.",
            "We kiezen voor één computer.",
            "We besluiten niet naar een cloudserver te gaan.",
        ):
            with self.subTest(text=text):
                result = extract_rules(text, "s1")
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["type"], "decision")
                self.assertEqual(set(result[0]), {"type", "title", "text", "source_segment_ids"})

    def test_questions_keep_their_original_content(self):
        for text in (
            "Hoe bewaren we de bronverwijzingen?",
            "Ik vraag me af of whisper.cpp snel genoeg is.",
            "Maar ondersteunt Unity dit op Linux?",
            "Kunnen we dit ook zonder internet gebruiken",
            "Of Unity ook vanaf de externe SSD werkt",
        ):
            with self.subTest(text=text):
                result = extract_rules(text, "s1")
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["type"], "question")
                self.assertEqual(result[0]["text"], text)

    def test_actions_require_a_clear_cue(self):
        for text in (
            "Onderzoek of dit met Unity kan.",
            "Volgende stap: test de microfoon op deze computer.",
            "We moeten de prestaties eerst meten.",
            "Ik zal morgen de documentatie bekijken.",
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_rules(text, "s1")[0]["type"], "action")

    def test_empty_or_noise_does_not_produce_a_card(self):
        for text in ("", " \n\t", "[stilte]", "(onverstaanbaar)", "uhm", "Ja.", "...", "12 25"):
            with self.subTest(text=text):
                self.assertEqual(extract_rules(text, "s1"), [])

    def test_unrecognised_chatter_is_not_an_invented_idea(self):
        self.assertEqual(extract_rules("Dat klopt inderdaad. Bedankt voor het gesprek.", "s1"), [])

    def test_duplicate_sentences_are_removed_but_distinct_questions_remain(self):
        result = extract_rules("Werkt Unity?\nwerkt Unity!\nWerkt Blender?", "s1")
        self.assertEqual(len(result), 2)
        self.assertEqual([x["text"] for x in result], ["Werkt Unity?", "Werkt Blender?"])

    def test_numbered_and_bulleted_notes_keep_technical_names(self):
        result = extract_rules("1. Idee: whisper.cpp op een externe SSD.\n- Test Unity Hub op Linux.", "s1")
        self.assertEqual([x["type"] for x in result], ["idea", "action"])
        self.assertEqual(result[0]["text"], "Idee: whisper.cpp op een externe SSD.")

    def test_long_output_and_card_count_are_bounded_without_inventing_text(self):
        sentences = ["Idee: " + ("lokaal " * 500)] + [f"Onderzoek onderwerp {i}." for i in range(20)]
        text = "\n".join(sentences)
        result = extract_rules(text, "s1")
        self.assertEqual(len(result), 12)
        self.assertTrue(all(0 < len(c["title"]) <= 120 and len(c["text"]) <= 2000 for c in result))
        self.assertTrue(all(c["title"] in c["text"] and c["text"] in text for c in result))

    def test_calls_do_not_share_mutable_candidates_or_source_arrays(self):
        text = "We willen een draagbare ontwikkelomgeving."
        original = deepcopy(text)
        first = extract_rules(text, "s1")
        first[0]["source_segment_ids"].append("unexpected")
        first[0]["text"] = "changed"
        second = extract_rules(text, "s1")
        self.assertEqual(text, original)
        self.assertEqual(second[0]["text"], text)
        self.assertEqual(second[0]["source_segment_ids"], ["s1"])

    def test_invalid_direct_calls_fail_instead_of_producing_fake_source_ids(self):
        with self.assertRaises(ValueError):
            extract_rules("We willen een bord.", "")
        with self.assertRaises(TypeError):
            extract_rules(None, "s1")


if __name__ == "__main__":
    unittest.main()
