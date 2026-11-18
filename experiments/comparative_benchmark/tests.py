"""Checks that protect the validity of the experiments, without model downloads."""

import unittest

from experiments.comparative_benchmark.common import (
    OUT,
    read_json,
    setup,
    sha,
    verify_production_unchanged,
)


class ResearchProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup()

    def test_speaker_metrics_do_not_reward_false_acceptance(self):
        import numpy as np

        from experiments.comparative_benchmark.speaker import metric_arrays

        truth = np.array([[0, 1, 2, 3, 4, 5, 5, 5, 5, 5]])
        correct = metric_arrays(truth, truth)
        self.assertEqual(correct["macro_f1"][0], 1.0)
        accepted = truth.copy()
        accepted[0, 5:] = 0
        metrics = metric_arrays(truth, accepted)
        self.assertEqual(metrics["false_accept_rate"][0], 1.0)
        self.assertEqual(metrics["unknown_rejection"][0], 0.0)
        self.assertLess(metrics["macro_f1"][0], 1.0)

    def test_knn_rejection_uses_distance_not_saturated_vote(self):
        import numpy as np

        from experiments.comparative_benchmark.speaker import episode_scores

        vectors = {str(i): np.eye(6, dtype=np.float32)[i] for i in range(6)}
        e = {
            "known": [str(i) for i in range(5)],
            "k": 1,
            "support": {str(i): [str(i)] for i in range(5)},
            "queries": [{"id": "5", "speaker": "outsider", "known": False}],
        }
        _, score, _, truth = episode_scores(vectors, e, "cosine_knn", 1)
        self.assertEqual(float(score[0]), 0.0)
        self.assertEqual(int(truth[0]), 5)

    def test_vad_false_alarm_is_penalized(self):
        import numpy as np

        from experiments.comparative_benchmark.segmentation import binary_counts, metrics

        truth = np.array([True, False, False, True])
        result = metrics(binary_counts(truth, np.ones(4, dtype=bool)))
        self.assertEqual(result["fp"], 2)
        self.assertLess(result["f1"], 1.0)

    def test_speaker_splits_and_enrollment_are_disjoint(self):
        manifest = read_json(OUT / "speaker/manifests.json")
        groups = []
        for split in ("development", "validation", "test"):
            episodes = manifest[f"vivos_{split}"]
            groups.append({q["speaker"] for e in episodes for q in e["queries"]})
            for e in episodes:
                self.assertFalse(set(e["known"]) & set(e["unknown"]))
                self.assertFalse(
                    {i for ids in e["support"].values() for i in ids}
                    & {q["id"] for q in e["queries"]}
                )
        for i, a in enumerate(groups):
            for b in groups[i + 1 :]:
                self.assertFalse(a & b)

    def test_synthetic_queries_do_not_reuse_enrollment_origins(self):
        manifest = read_json(OUT / "speaker_synthetic/manifests.json")
        for episodes in manifest.values():
            for e in episodes:
                support = {i for ids in e["support"].values() for i in ids}
                self.assertFalse(support & {q["id"].split("__")[0] for q in e["queries"]})

    def test_synthetic_asr_has_verified_audio_and_paired_labels(self):
        manifest = [
            r for r in read_json(OUT / "asr/manifest.json") if r["split"].startswith("synthetic_")
        ]
        from pathlib import Path

        paired = {}
        for row in manifest:
            self.assertEqual(sha(Path(row["audio_path"])), row["audio_sha256"])
            paired.setdefault(row["meeting_id"], []).append(row)
        self.assertEqual(len(paired), 39)
        for rows in paired.values():
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["reference"], rows[1]["reference"])
            self.assertEqual(rows[0]["origin_id"], rows[1]["origin_id"])

    def test_text_templates_do_not_leak_between_splits(self):
        docs = read_json(OUT / "text/manifest.json")
        groups = [
            {u["template_id"] for d in docs if d["split"] == s for u in d["units"]}
            for s in ("development", "validation", "test")
        ]
        for i, a in enumerate(groups):
            for b in groups[i + 1 :]:
                self.assertFalse(a & b)

    def test_production_source_is_unchanged(self):
        self.assertTrue(verify_production_unchanged()["passed"])

    def test_paired_bootstrap_identical_predictions_have_zero_delta(self):
        from experiments.comparative_benchmark.paired_statistics import bootstrap_delta

        result = bootstrap_delta([[3, 3, 10], [2, 2, 7]], draws=100)
        self.assertEqual((result["delta"], result["ci_low"], result["ci_high"]), (0, 0, 0))

    def test_separation_score_does_not_penalize_global_gain(self):
        import numpy as np

        from experiments.comparative_benchmark.separation import si_sdr

        wave = np.random.default_rng(7).normal(size=1000)
        self.assertGreater(si_sdr(wave, 0.25 * wave), 100)

    def test_incomplete_ocr_alphabet_is_excluded_from_recommendations(self):
        from experiments.comparative_benchmark.reviews import refresh

        row = next(r for r in refresh() if r["model"] == "paddle_latin_v5")
        self.assertFalse(row["eligible_for_full_Vietnamese_orthography"])
        self.assertEqual(
            row["recommendation"], "select_checkpoint_with_complete_Vietnamese_alphabet_first"
        )

    def test_error_analysis_matches_frozen_published_asr_scores(self):
        rows = read_json(OUT / "ASR_error_analysis.json")["summary"]
        self.assertEqual(len(rows), 5)
        for row in rows:
            summary = read_json(OUT / f"asr_mps_float16/{row['model']}/synthetic_test_summary.json")
            frozen = next(r for r in summary if r["condition"] == "simulated_only")
            self.assertAlmostEqual(row["published_wer"], frozen["wer"])

    def test_native_fusion_replay_reproduces_pipeline_baseline(self):
        rows = [
            r
            for r in read_json(OUT / "fusion_native/predictions.json")
            if r["method"] == "F5_RULE_WEIGHTED_CORRECTED"
        ]
        baseline = {r["case"]: r for r in read_json(OUT / "core_replay/baseline/summary.json")}
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertAlmostEqual(row["wer"], baseline[row["case"]]["wer"])


if __name__ == "__main__":
    unittest.main()
