"""Streamlit interactive demo application for Multi-Device Meeting Pipeline.

Specification: Section 14 & 21 of docs/PLAN_VIVOS_SYNTHETIC_PIPELINE.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

st.set_page_config(
    page_title="Multi-Device Meeting Transcription & Fusion",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.0rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_json(path: Path) -> Any:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def main() -> None:
    st.markdown(
        '<div class="main-header">🎙️ Multi-Device Meeting Pipeline (VIVOS Corpus)</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-header">Hệ thống đồng bộ, định danh người nói và hợp nhất '
        "bản phiên âm đa thiết bị với cơ chế truy vết nguồn gốc (Word Provenance).</div>",
        unsafe_allow_html=True,
    )

    st.sidebar.header("⚙️ Cấu hình & Dữ liệu")
    generated_base = Path("data/generated/smoke")
    available_meetings: list[str] = []
    if generated_base.exists():
        available_meetings = sorted([p.name for p in generated_base.iterdir() if p.is_dir()])

    if not available_meetings:
        st.warning("Chưa tìm thấy dữ liệu cuộc họp trong `data/generated/smoke/`.")
        selected_meeting = "meeting_test_001"
    else:
        selected_meeting = st.sidebar.selectbox(
            "Chọn cuộc họp:",
            available_meetings,
            index=len(available_meetings) - 1,
        )

    meeting_audio_dir = generated_base / selected_meeting
    timeline_file = Path("artifacts/smoke") / selected_meeting / "final_timeline.json"
    summary_file = Path("reports/metrics/summary.json")

    timeline_data = load_json(timeline_file)
    summary_data = load_json(summary_file)

    tab_timeline, tab_audio, tab_baselines, tab_metrics, tab_provenance = st.tabs(
        [
            "📋 Dòng sự kiện (Timeline)",
            "🎧 Âm thanh đa kênh",
            "🔀 So sánh 7 Baselines",
            "📊 Báo cáo & Metrics",
            "🔍 Truy vết nguồn gốc (Provenance)",
        ]
    )

    with tab_timeline:
        st.subheader("Dòng sự kiện cuộc họp sau hợp nhất (Final Timeline)")
        if timeline_data:
            st.info(f"Tổng số phân đoạn lời nói phát hiện: **{len(timeline_data)}**")
            for idx, item in enumerate(timeline_data):
                spk = item.get("speaker_id", "unknown")
                conf = item.get("speaker_confidence", 0.0)
                start_t = item.get("start_sec", 0.0)
                end_t = item.get("end_sec", 0.0)
                text = item.get("fused_text", "")
                primary_dev = item.get("primary_source_id", "unknown")
                t_conf = item.get("transcript_confidence", 0.0)

                label = (
                    f"⏱️ [{start_t:05.2f}s - {end_t:05.2f}s] {spk} "
                    f"({conf:.1%}) | Primary: {primary_dev}"
                )
                with st.expander(label, expanded=(idx < 2)):
                    st.markdown(f'**Bản phiên âm hợp nhất:**\n> *"{text}"*')
                    st.write(f"- Độ dài phân đoạn: `{end_t - start_t:.2f}s`")
                    st.write(f"- Thiết bị đại diện (Primary Source): `{primary_dev}`")
                    st.write(f"- Độ tin cậy phiên âm: `{t_conf:.2f}`")

                    clips = item.get("evidence_clips", {})
                    if clips and primary_dev in clips:
                        clip_p = Path(clips[primary_dev])
                        if clip_p.exists():
                            st.audio(str(clip_p), format="audio/wav")
        else:
            st.info("Chưa có artifact `final_timeline.json`. Vui lòng chạy `evaluate run` trước.")

    with tab_audio:
        st.subheader("Bản ghi âm thanh từ các thiết bị phân tán")
        if meeting_audio_dir.exists():
            wav_files = sorted(list(meeting_audio_dir.glob("*.wav")))
            cols = st.columns(min(len(wav_files), 3) or 1)
            for i, wav_path in enumerate(wav_files):
                col = cols[i % len(cols)]
                with col:
                    st.markdown(f"**Channel:** `{wav_path.name}`")
                    st.audio(str(wav_path), format="audio/wav")
                    st.caption(f"Kích thước: {wav_path.stat().st_size / 1024:.1f} KB")
        else:
            st.warning(f"Thư mục âm thanh không tồn tại tại `{meeting_audio_dir}`")

    with tab_baselines:
        st.subheader("So sánh 7 Baselines hợp nhất bản phiên âm (F0 - F6)")
        st.markdown(
            """
            - **F0_FIXED**: Chọn thiết bị cố định (kênh 1).
            - **F1_BEST_SEGMENT**: Chọn kênh có chất lượng tín hiệu cao nhất theo phân đoạn.
            - **F2_ORACLE_BEST**: Chọn kênh có WER thấp nhất so với ground truth.
            - **F3_ROVER**: Bỏ phiếu đa số theo Confusion Network.
            - **F4_ASR_WEIGHTED**: Bỏ phiếu theo độ tin cậy PhoWhisper.
            - **F5_RULE_WEIGHTED**: Bỏ phiếu kết hợp chất lượng âm học và độ tin cậy ASR.
            - **F6_LEARNED**: Mô hình Logistic Regression phân loại token chuẩn.
            """
        )
        table_path = Path("reports/tables/baselines_comparison.md")
        if table_path.exists():
            st.markdown(table_path.read_text(encoding="utf-8"))
        elif summary_data and "asr_fusion_baselines" in summary_data:
            st.json(summary_data["asr_fusion_baselines"])
        else:
            st.info("Chưa có báo cáo so sánh baselines. Hãy chạy `evaluate run`.")

    with tab_metrics:
        st.subheader("Báo cáo đánh giá tổng thể (Milestone 7)")
        if summary_data:
            m1, m2, m3, m4 = st.columns(4)
            sync_info = summary_data.get("synchronization", {})
            vad_info = summary_data.get("vad", {})
            spk_info = summary_data.get("speaker_identification", {}).get("30s", {})
            f5_info = summary_data.get("asr_fusion_baselines", {}).get("F5_RULE_WEIGHTED", {})

            with m1:
                st.metric("Sync MAE (Lệch thời gian)", f"{sync_info.get('mae_ms', 0.0):.2f} ms")
            with m2:
                st.metric("VAD Frame F1-Score", f"{vad_info.get('frame_f1', 0.0):.1%}")
            with m3:
                st.metric("Speaker ID (30s Acc)", f"{spk_info.get('accuracy', 0.0):.1%}")
            with m4:
                st.metric("ASR WER (F5 Rule-Weighted)", f"{f5_info.get('wer', 0.0):.1%}")

            st.markdown("---")
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown("### 👤 Độ chính xác định danh theo Enrollment")
                spk_table_path = Path("reports/tables/speaker_id_by_enrollment.md")
                if spk_table_path.exists():
                    st.markdown(spk_table_path.read_text(encoding="utf-8"))

            with col_r:
                st.markdown("### ⚠️ Phân tích các trường hợp lỗi")
                fail_table_path = Path("reports/failure_cases/failure_analysis.md")
                if fail_table_path.exists():
                    st.markdown(fail_table_path.read_text(encoding="utf-8"))
        else:
            st.info("Chưa có tệp tổng hợp `reports/metrics/summary.json`.")

    with tab_provenance:
        st.subheader("Truy vết nguồn gốc từng từ ngữ (Word-Level Provenance)")
        st.markdown(
            "Cơ chế cho phép người dùng kiểm tra nguồn gốc từ từng thiết bị đóng góp "
            "vào kết quả cuối cùng."
        )

        if timeline_data:
            seg_indices = [
                f"#{i + 1}: {item.get('fused_text', '')[:35]}..."
                for i, item in enumerate(timeline_data)
            ]
            selected_idx = st.selectbox(
                "Chọn phân đoạn chi tiết:",
                range(len(seg_indices)),
                format_func=lambda i: seg_indices[i],
            )
            chosen_item = timeline_data[selected_idx]

            st.markdown(f'**Bản phiên âm:** *"{chosen_item.get("fused_text")}"*')
            st.markdown(
                f"**Người nói:** `{chosen_item.get('speaker_id')}` | "
                f"**Primary Device:** `{chosen_item.get('primary_source_id')}`"
            )

            word_provs = chosen_item.get("word_provenance", [])
            if word_provs:
                st.markdown("#### Bảng phân tích chi tiết từng từ:")
                table_rows = []
                for wp in word_provs:
                    table_rows.append(
                        {
                            "Từ (Token)": wp.get("output_word"),
                            "Độ tin cậy": f"{wp.get('confidence', 0.0):.2f}",
                            "Các thiết bị hỗ trợ": ", ".join(wp.get("supporting_sources", [])),
                            "Thiết bị đại diện": wp.get("representative_source_id"),
                        }
                    )
                st.table(table_rows)

            clips = chosen_item.get("evidence_clips", {})
            if clips:
                st.markdown("#### Nghe lại đoạn âm thanh bằng chứng:")
                clip_cols = st.columns(len(clips))
                for idx, (dev_name, clip_path_str) in enumerate(clips.items()):
                    with clip_cols[idx]:
                        st.markdown(f"**{dev_name}**")
                        if Path(clip_path_str).exists():
                            st.audio(clip_path_str, format="audio/wav")
        else:
            st.info("Chưa có timeline artifact để kiểm tra provenance.")


if __name__ == "__main__":
    main()
