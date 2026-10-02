from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from meeting_pipeline.datasets.subset import build_voxvietnam_subset_index


def test_support_and_query_rows_are_disjoint(tmp_path: Path) -> None:
    shard = tmp_path / "part.parquet"
    pq.write_table(pa.table({"speaker": ["a"] * 12 + ["b"] * 9}), shard)
    payload = build_voxvietnam_subset_index([shard], tmp_path / "index.json", seed=7)
    speakers = payload["speakers"]
    assert isinstance(speakers, dict)
    assert set(speakers) == {"a"}
    support = {item["row_index"] for item in speakers["a"]["support_pool"]}
    query = {item["row_index"] for item in speakers["a"]["query_pool"]}
    assert support.isdisjoint(query)
