import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Database,
  FileSpreadsheet,
  Lock,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  FilterBar,
  Notice,
  PageHeader,
  Panel,
} from "@/components/common";
import { PublicLayout } from "@/components/layouts";
import { Reveal } from "@/components/visuals/ambient";
import { api, size } from "@/lib/api";
import type { Capabilities, User } from "@/lib/types";

export { WelcomeExperience as WelcomePage } from "./welcome";

export function GuidePage({ user }: { user?: User | null }) {
  const capabilities = useQuery({
    queryKey: ["public-capabilities"],
    queryFn: () => api<Capabilities>("/capabilities"),
    enabled: Boolean(user),
    retry: false,
  });

  const maxSources = capabilities.data?.max_source_files ?? 8;
  const maxClips = capabilities.data?.max_timeline_clips ?? 32;
  const maxDurationMin = Math.round(
    (capabilities.data?.max_audio_duration_sec ?? 7200) / 60,
  );
  const maxUploadText = capabilities.data?.max_upload_bytes
    ? size(capabilities.data.max_upload_bytes)
    : "500 MB";

  return (
    <PublicLayout user={user}>
      <div className="page-container--form public-editorial">
        <PageHeader
          eyebrow="TÀI LIỆU HƯỚNG DẪN"
          title="Hướng dẫn sử dụng Minda từ đầu đến cuối"
          description="Quy trình chuẩn bị tệp âm thanh, mẫu biên bản, rà soát lời chép và kiểm tra biên bản Word."
          action={
            <Button asChild>
              <Link to={user ? "/meetings/new" : "/login"}>
                {user ? "Tạo cuộc họp mới" : "Đăng nhập để bắt đầu"}
              </Link>
            </Button>
          }
        />

        <nav className="guide-toc" aria-label="Các bước hướng dẫn">
          <a href="#guide-1">01 Chuẩn bị</a>
          <a href="#guide-2">02 Nguồn âm thanh</a>
          <a href="#guide-3">03 Lời chép</a>
          <a href="#guide-4">04 Biên bản</a>
        </nav>
        <div className="guide-intro-art">
          <img
            src="/illustrations/signal.webp"
            alt="Minh họa nhiều nguồn âm thanh hội tụ"
            width="1200"
            height="900"
          />
        </div>
        <Panel
          id="guide-1"
          className="guide-step guide-step-1"
          title="1. Chuẩn bị file âm thanh và mẫu biên bản"
          description="Định dạng hỗ trợ và giới hạn kỹ thuật theo cấu hình máy chủ hiện hành."
        >
          <div className="stack">
            <p>
              Hệ thống chấp nhận các định dạng âm thanh phổ biến (WAV, MP3, M4A,
              FLAC, OGG, AAC, WebM) và mẫu biên bản dạng Word (
              <code>.docx</code>
              ), PDF hoặc ảnh chụp tài liệu (khi bật OCR).
            </p>
            <div className="minda-table-wrap">
              <table className="minda-table">
                <thead>
                  <tr>
                    <th>Thông số giới hạn</th>
                    <th>Giá trị cấu hình hiện tại</th>
                    <th>Lưu ý vận hành</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Số file nguồn tối đa mỗi cuộc họp</td>
                    <td>
                      <strong>
                        {capabilities.data
                          ? `${maxSources} file`
                          : "Theo cấu hình máy chủ"}
                      </strong>
                    </td>
                    <td>Hỗ trợ ghép nối tuần tự hoặc đồng bộ nhiều thiết bị</td>
                  </tr>
                  <tr>
                    <td>Số đoạn (clip) trên timeline</td>
                    <td>
                      <strong>
                        {capabilities.data
                          ? `${maxClips} đoạn`
                          : "Theo cấu hình máy chủ"}
                      </strong>
                    </td>
                    <td>Có thể cắt bỏ đoạn thử mic hoặc giải lao</td>
                  </tr>
                  <tr>
                    <td>Tổng thời lượng âm thanh tối đa</td>
                    <td>
                      <strong>
                        {capabilities.data
                          ? `${maxDurationMin} phút`
                          : "Theo cấu hình máy chủ"}
                      </strong>
                    </td>
                    <td>Tính trên tổng thời lượng các đoạn đưa vào xử lý</td>
                  </tr>
                  <tr>
                    <td>Dung lượng tải lên mỗi lần</td>
                    <td>
                      <strong>
                        {capabilities.data
                          ? maxUploadText
                          : "Theo cấu hình máy chủ"}
                      </strong>
                    </td>
                    <td>File gốc được lưu nguyên vẹn để phát đối chiếu</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </Panel>

        <Panel
          id="guide-2"
          className="guide-step guide-step-2"
          title="2. Tạo cuộc họp và sắp xếp nguồn âm thanh"
          description="Thực hiện tại màn hình Tạo cuộc họp (/meetings/new) và tab Nguồn âm thanh (?tab=sources)."
        >
          <ol
            className="guide-list"
            style={{ paddingLeft: 20, display: "grid", gap: 10 }}
          >
            <li>
              <strong>Khai báo thông tin cơ bản:</strong> Nhập tiêu đề cuộc họp,
              ngày họp (hiển thị theo định dạng <code>dd/mm/yyyy</code>), địa
              điểm và ghi chú bối cảnh.
            </li>
            <li>
              <strong>Tải lên nguồn âm thanh:</strong> Chọn một hoặc nhiều file
              ghi âm. Lưu ý: nếu tải lại trình duyệt giữa chừng ở bước tạo mới,
              thông tin chữ được giữ nháp nhưng tệp âm thanh từ máy tính cần
              được chọn lại để trình duyệt cấp quyền đọc file.
            </li>
            <li>
              <strong>Thiết lập timeline và khoảng nghỉ:</strong> Tại tab{" "}
              <em>Nguồn âm thanh</em>, bạn có thể chỉnh điểm đầu/cuối của từng
              clip bằng nút điều khiển hoặc nhập số giây chính xác, khai báo mốc
              giờ bắt đầu thực tế và đánh dấu khoảng giải lao.
            </li>
          </ol>
        </Panel>

        <Panel
          id="guide-3"
          className="guide-step guide-step-3"
          title="3. Rà soát lời chép và định danh người nói"
          description="Thực hiện tại tab Lời chép (?tab=transcript) và chế độ Người nói (?tab=speakers)."
        >
          <ol
            className="guide-list"
            style={{ paddingLeft: 20, display: "grid", gap: 10 }}
          >
            <li>
              <strong>Lọc nhanh các đoạn cần kiểm tra:</strong> Bật bộ lọc{" "}
              <em>Chỉ phần cần rà</em> hoặc tìm từ khóa trên toàn bộ lời chép
              (không bị giới hạn ở trang đang mở).
            </li>
            <li>
              <strong>Nghe đối chiếu và sửa nội dung:</strong> Nhấn nút{" "}
              <em>Nghe</em> trên từng đoạn để phát đúng vị trí âm thanh, nhấn{" "}
              <em>Sửa</em> để hiệu đính câu chữ. Mỗi lần lưu tạo một bản ghi
              phiên bản an toàn và giữ nguyên mốc thời gian gốc.
            </li>
            <li>
              <strong>Gán tên người nói:</strong> Chuyển sang chế độ{" "}
              <em>Người nói</em> để đổi nhãn đồng loạt cho một cụm giọng nói,
              hoặc liên kết với{" "}
              <Link to="/voices" className="green-text">
                Hồ sơ giọng
              </Link>{" "}
              đã đăng ký trước.
            </li>
          </ol>
        </Panel>

        <Panel
          id="guide-4"
          className="guide-step guide-step-4"
          title="4. Tạo biên bản, kiểm tra căn cứ và xuất file Word"
          description="Thực hiện tại tab Biên bản (?tab=minutes) và Lịch sử (?tab=history)."
        >
          <ol
            className="guide-list"
            style={{ paddingLeft: 20, display: "grid", gap: 10 }}
          >
            <li>
              <strong>Chọn mẫu và tạo biên bản:</strong> Chọn mẫu biên bản cá
              nhân hoặc dùng chung, chọn chế độ chi tiết/tổng hợp và chuẩn thể
              thức (NĐ 30/2020 hoặc HD 05/2026) rồi gửi tác vụ xử lý.
            </li>
            <li>
              <strong>Sửa theo từng mục kèm căn cứ:</strong> Nhấn vào từng
              trường thông tin để xem đoạn lời chép làm căn cứ ở cột bên phải và
              nghe lại trực tiếp. Khi lời chép thay đổi sau khi tạo biên bản, hệ
              thống sẽ gắn nhãn <em>Cần cập nhật</em> để bạn chủ động đối chiếu.
            </li>
            <li>
              <strong>Xem trước và tải Word:</strong> Chuyển sang chế độ{" "}
              <em>Xem trước Word</em> để kiểm tra bố cục trang (hỗ trợ thu phóng
              50%–200% hoặc vừa khung), xác nhận đã rà soát và tải file{" "}
              <code>.docx</code> về máy.
            </li>
          </ol>
        </Panel>
      </div>
    </PublicLayout>
  );
}

interface HelpArticle {
  id: string;
  category: "audio" | "template" | "transcript" | "minutes" | "account";
  categoryLabel: string;
  question: string;
  answer: string;
  routeLabel: string;
  routeTo: string;
}

const HELP_ARTICLES: HelpArticle[] = [
  {
    id: "audio-1",
    category: "audio",
    categoryLabel: "Audio",
    question: "Làm sao xử lý khi cuộc họp có nhiều file ghi âm rời nhau?",
    answer:
      "Bạn tải tất cả các file vào tab Nguồn âm thanh của cuộc họp. Nếu các file ghi nối tiếp trên cùng một máy, hãy đặt trên một track theo thứ tự sequential. Nếu ghi song song từ nhiều máy, đặt trên các track riêng và chạy căn chỉnh mốc thời gian.",
    routeLabel: "Xem danh sách cuộc họp",
    routeTo: "/meetings",
  },
  {
    id: "audio-2",
    category: "audio",
    categoryLabel: "Audio",
    question: "Vì sao một số đoạn lời chép không phát được clip riêng?",
    answer:
      "Khi file âm thanh nguồn chưa có khoảng cắt hợp lệ hoặc mốc thời gian đang ở trạng thái ước lượng/chưa xác định, nút nghe sẽ hiển thị rõ lý do. Bạn vẫn có thể mở nguồn âm thanh gốc ở thanh phát để kiểm tra.",
    routeLabel: "Xem hướng dẫn chuẩn bị file",
    routeTo: "/guide",
  },
  {
    id: "template-1",
    category: "template",
    categoryLabel: "Mẫu/OCR",
    question: "Khi nào mẫu biên bản cần OCR và duyệt thủ công?",
    answer:
      "Nếu bạn tải lên mẫu dạng PDF scan hoặc ảnh chụp, hệ thống sẽ chạy OCR để trích xuất văn bản và các trường điền thông tin. Sau khi đọc xong, mẫu được chuyển sang trạng thái Cần rà soát để bạn kiểm tra nhãn trường trước khi áp dụng.",
    routeLabel: "Quản lý mẫu biên bản",
    routeTo: "/templates",
  },
  {
    id: "template-2",
    category: "template",
    categoryLabel: "Mẫu/OCR",
    question: "Sự khác nhau giữa mẫu cá nhân và mẫu dùng chung là gì?",
    answer:
      "Mẫu cá nhân chỉ hiển thị và chỉnh sửa trong tài khoản của bạn. Mẫu dùng chung do quản trị viên phát hành để mọi thành viên trong đơn vị sử dụng thống nhất; người dùng thường có thể chọn mẫu chung nhưng không sửa trực tiếp cấu trúc gốc.",
    routeLabel: "Nhập mẫu mới",
    routeTo: "/templates/new",
  },
  {
    id: "transcript-1",
    category: "transcript",
    categoryLabel: "Lời chép",
    question:
      "Sửa văn bản trong lời chép có làm mất mốc thời gian âm thanh không?",
    answer:
      "Không. Khi bạn sửa chính tả hoặc thuật ngữ trong một đoạn, hệ thống lưu phiên bản lời chép mới nhưng giữ nguyên mốc bắt đầu/kết thúc và liên kết tới bản ghi âm gốc.",
    routeLabel: "Mở hàng đợi cần rà soát",
    routeTo: "/review",
  },
  {
    id: "transcript-2",
    category: "transcript",
    categoryLabel: "Lời chép",
    question: "Làm sao phân biệt giọng người lạ, chưa xác định và nói chồng?",
    answer:
      "Trong tab Lời chép và chế độ Người nói, hệ thống giữ nguyên nhãn nghiệp vụ (Đã gán hồ sơ, Cụm giọng chưa đặt tên, Không rõ người nói, hoặc Nói chồng nhiều người) để bạn nghe mẫu đoạn trước khi đổi nhãn.",
    routeLabel: "Quản lý hồ sơ giọng",
    routeTo: "/voices",
  },
  {
    id: "minutes-1",
    category: "minutes",
    categoryLabel: "Biên bản",
    question: "Vì sao biên bản hiện cảnh báo 'Cần cập nhật' (stale)?",
    answer:
      "Cảnh báo này xuất hiện khi nguồn âm thanh hoặc lời chép đã được chỉnh sửa sau thời điểm biên bản hiện tại được tạo. Bạn có thể xem lại từng mục, tạo lại biên bản theo lời chép mới, hoặc đối chiếu trong tab Lịch sử.",
    routeLabel: "Mở thư viện biên bản",
    routeTo: "/documents",
  },
  {
    id: "minutes-2",
    category: "minutes",
    categoryLabel: "Biên bản",
    question: "Đổi thể thức văn bản khác gì với Tạo lại biên bản?",
    answer:
      "Đổi thể thức (ví dụ giữa NĐ 30/2020 và HD 05/2026) chỉ kết xuất lại tệp Word dựa trên các trường thông tin đã có. Ngược lại, Tạo lại biên bản sẽ trích xuất lại nội dung từ lời chép hiện hành.",
    routeLabel: "Xem tác vụ xử lý",
    routeTo: "/jobs",
  },
  {
    id: "account-1",
    category: "account",
    categoryLabel: "Tài khoản",
    question: "Quên mật khẩu hoặc tài khoản bị khóa thì khôi phục thế nào?",
    answer:
      "Minda vận hành trong mạng nội bộ và không tự động gửi email ra ngoài. Khi cần cấp mới tài khoản, mở khóa hoặc đặt lại mật khẩu, hãy liên hệ trực tiếp quản trị viên hệ thống.",
    routeLabel: "Xem hướng dẫn hỗ trợ tài khoản",
    routeTo: "/account-help",
  },
  {
    id: "account-2",
    category: "account",
    categoryLabel: "Tài khoản",
    question: "Đổi mật khẩu cá nhân có đăng xuất các phiên đang mở không?",
    answer:
      "Có. Ngay khi đổi mật khẩu tại trang Thiết lập, mọi phiên đăng nhập cũ sẽ bị thu hồi để bảo đảm an toàn và bạn sẽ đăng nhập lại bằng mật khẩu mới.",
    routeLabel: "Mở trang thiết lập",
    routeTo: "/settings",
  },
];

const HELP_CATEGORIES: {
  id: "all" | HelpArticle["category"];
  label: string;
}[] = [
  { id: "all", label: "Tất cả nhóm" },
  { id: "audio", label: "Audio" },
  { id: "template", label: "Mẫu/OCR" },
  { id: "transcript", label: "Lời chép" },
  { id: "minutes", label: "Biên bản" },
  { id: "account", label: "Tài khoản" },
];

export function HelpPage({ user }: { user?: User | null }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<"all" | HelpArticle["category"]>(
    "all",
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("vi");
    return HELP_ARTICLES.filter((item) => {
      if (category !== "all" && item.category !== category) return false;
      if (!q) return true;
      return (
        item.question.toLocaleLowerCase("vi").includes(q) ||
        item.answer.toLocaleLowerCase("vi").includes(q) ||
        item.categoryLabel.toLocaleLowerCase("vi").includes(q)
      );
    });
  }, [query, category]);

  return (
    <PublicLayout user={user}>
      <div className="page-container--form public-editorial">
        <PageHeader
          eyebrow="TRUNG TÂM TRỢ GIÚP"
          title="Câu hỏi thường gặp & xử lý tình huống"
          description="Tra cứu nhanh theo nhóm chức năng Audio, Mẫu/OCR, Lời chép, Biên bản và Tài khoản."
          action={
            <div className="row wrap">
              <Button asChild variant="outline">
                <Link to="/guide">
                  <BookOpen size={16} />
                  Hướng dẫn đầy đủ
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/account-help">Hỗ trợ tài khoản</Link>
              </Button>
            </div>
          }
        />

        <FilterBar
          searchValue={query}
          onSearchChange={setQuery}
          searchPlaceholder="Tìm câu hỏi hoặc từ khóa (ví dụ: OCR, stale, mật khẩu)…"
          searchLabel="Tìm kiếm câu hỏi trợ giúp"
          hasActiveFilters={Boolean(query.trim()) || category !== "all"}
          onReset={() => {
            setQuery("");
            setCategory("all");
          }}
          filters={
            <div
              className="minda-filter-pills"
              role="group"
              aria-label="Nhóm trợ giúp"
            >
              {HELP_CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  className={
                    "minda-filter-pill" + (category === cat.id ? " active" : "")
                  }
                  onClick={() => setCategory(cat.id)}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          }
          summary={`${filtered.length} bài hướng dẫn`}
        />

        {filtered.length ? (
          <div className="stack">
            {filtered.map((item) => (
              <details
                key={item.id}
                className="panel help-article"
                style={{ marginBottom: 0 }}
              >
                <div className="row between wrap" style={{ marginBottom: 8 }}>
                  <span className="status-badge info">
                    {item.categoryLabel}
                  </span>
                  <Link to={item.routeTo} className="small green-text">
                    {item.routeLabel}
                    <ArrowRight size={14} />
                  </Link>
                </div>
                <summary>{item.question}</summary>
                <p className="muted" style={{ marginTop: 8 }}>
                  {item.answer}
                </p>
              </details>
            ))}
          </div>
        ) : (
          <Empty
            title="Không tìm thấy câu hỏi phù hợp"
            description="Hãy thử từ khóa khác hoặc chuyển về 'Tất cả nhóm' để xem toàn bộ danh mục trợ giúp."
            action={
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setQuery("");
                  setCategory("all");
                }}
              >
                Hiển thị tất cả câu hỏi
              </Button>
            }
          />
        )}
      </div>
    </PublicLayout>
  );
}

export function DataPolicyPage({ user }: { user?: User | null }) {
  return (
    <PublicLayout user={user}>
      <div className="page-container--reading public-editorial">
        <PageHeader
          eyebrow="DỮ LIỆU & QUẢN TRỊ HỆ THỐNG"
          title="Chính sách lưu trữ dữ liệu và phân quyền truy cập"
          description="Giải thích minh bạch nơi lưu trữ, phạm vi truy cập, cơ chế xử lý nền, sao lưu và xóa mềm trên máy chủ triển khai Minda."
        />

        <Reveal className="policy-visual">
          <img
            src="/illustrations/evidence.webp"
            alt="Minh họa các lớp thông tin có liên kết và kiểm soát"
            width="1200"
            height="900"
          />
        </Reveal>
        <Notice tone="info">
          <strong>Lưu trữ tại máy chủ triển khai:</strong> Toàn bộ dữ liệu cuộc
          họp, file âm thanh, lời chép, mẫu biên bản và hồ sơ giọng được lưu trữ
          trên máy chủ nội bộ nơi đơn vị triển khai hệ thống (MongoDB và thư mục
          lưu trữ artifact của máy chủ), <strong>không</strong> phải chỉ lưu tạm
          trong trình duyệt cá nhân.
        </Notice>

        <Panel
          title="1. Dữ liệu được lưu trữ trên máy chủ"
          description="Các thành phần dữ liệu phát sinh trong quá trình sử dụng."
        >
          <div className="stack">
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <Database
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Cơ sở dữ liệu nghiệp vụ (MongoDB):</strong>
                <p className="muted">
                  Lưu thông tin tài khoản, phiên đăng nhập, metadata cuộc họp,
                  phiên bản lời chép, các trường thông tin biên bản, lịch sử tác
                  vụ (jobs) và nhật ký kiểm toán (audit logs).
                </p>
              </div>
            </div>
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <FileSpreadsheet
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Kho tệp đính kèm (Artifact Store trên máy chủ):</strong>
                <p className="muted">
                  Lưu bản ghi âm gốc, các đoạn cắt âm thanh đối chiếu, mẫu biên
                  bản tải lên, ảnh xem trước trang tài liệu và các bản xuất Word
                  (<code>.docx</code>) / gói lưu trữ (<code>.zip</code>).
                </p>
              </div>
            </div>
          </div>
        </Panel>

        <Panel
          title="2. Quyền sở hữu và phân tách dữ liệu"
          description="Kiểm soát truy cập ở cả tầng giao diện và tầng API."
        >
          <div className="stack">
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <Lock
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>
                  Dữ liệu cá nhân theo chủ sở hữu (Owner Isolation):
                </strong>
                <p className="muted">
                  Cuộc họp, lời chép, biên bản, hồ sơ giọng và mẫu cá nhân thuộc
                  quyền truy cập của chính tài khoản tạo ra. Mọi yêu cầu tải tệp
                  qua <code>/api/v1/artifacts/:id</code> đều kiểm tra quyền sở
                  hữu trước khi trả file.
                </p>
              </div>
            </div>
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <ShieldCheck
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Phạm vi của Quản trị viên (Admin):</strong>
                <p className="muted">
                  Quản trị viên quản lý danh sách tài khoản, cấu hình
                  model/preset, mẫu biên bản dùng chung, theo dõi hàng đợi tác
                  vụ, nhật ký vận hành và trạng thái lưu trữ; giao diện quản trị
                  chỉ hiển thị metadata vận hành và không tự ý mở nội dung cuộc
                  họp riêng của người dùng khác.
                </p>
              </div>
            </div>
          </div>
        </Panel>

        <Panel
          title="3. Xử lý tác vụ nền, sao lưu và xóa mềm"
          description="Bảo toàn lịch sử phiên bản và khả năng khôi phục."
        >
          <div className="stack">
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <RefreshCw
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Phiên bản hóa (Versioning & Revision Control):</strong>
                <p className="muted">
                  Khi chỉnh sửa lời chép hoặc biên bản, hệ thống kiểm tra số
                  revision để tránh ghi đè ngoài ý muốn (mã lỗi 409 Conflict) và
                  lưu thành phiên bản mới để có thể đối chiếu hoặc khôi phục
                  lại.
                </p>
              </div>
            </div>
            <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
              <Trash2
                size={20}
                className="muted"
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <div>
                <strong>Xóa mềm (Thùng rác) & Sao lưu hệ thống:</strong>
                <p className="muted">
                  Cuộc họp khi xóa được chuyển vào{" "}
                  <Link to="/trash" className="green-text">
                    Thùng rác
                  </Link>{" "}
                  (<code>trashed=true</code>) và chỉ cho phép xóa khi không có
                  tác vụ đang chạy. Người sở hữu có thể khôi phục bất cứ lúc
                  nào. Quản trị viên có thể tạo bản sao lưu toàn hệ thống và
                  kiểm thử khôi phục sang cơ sở dữ liệu/thư mục độc lập.
                </p>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </PublicLayout>
  );
}
