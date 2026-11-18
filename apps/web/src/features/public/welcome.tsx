import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  FileText,
  Headphones,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { PublicLayout } from "@/components/layouts";
import { AmbientVisual, Reveal } from "@/components/visuals/ambient";
import type { User } from "@/lib/types";

const features = [
  {
    id: "signal",
    number: "01",
    title: "Mọi nguồn âm thanh. Một dòng hội thoại.",
    text: "Sắp xếp nhiều bản ghi, khai báo mốc thời gian và nghe đối chiếu ngay trong không gian làm việc.",
    icon: Headphones,
  },
  {
    id: "evidence",
    number: "02",
    title: "Mỗi thông tin đều có nơi để đối chiếu.",
    text: "Đi từ một mục trong biên bản về đoạn lời chép làm căn cứ. Rà soát rõ ràng, chỉnh sửa có phiên bản.",
    icon: Sparkles,
  },
  {
    id: "document",
    number: "03",
    title: "Tài liệu chỉn chu. Sẵn sàng bàn giao.",
    text: "Áp dụng mẫu của đơn vị, kiểm tra trang in và xuất Word theo thể thức đã chọn.",
    icon: FileText,
  },
];

export function WelcomeExperience({ user }: { user?: User | null }) {
  const [tab, setTab] = useState<"transcript" | "minutes">("transcript");
  const appUrl = user ? (user.role === "admin" ? "/admin" : "/") : "/login";
  return (
    <PublicLayout user={user}>
      <div className="marketing-home">
        <section className="marketing-hero">
          <div className="hero-copy">
            <span className="marketing-kicker">
              <span /> KHÔNG GIAN CHO NHỮNG CUỘC HỌP RÕ RÀNG
            </span>
            <h1>
              Từ lời nói.
              <br />
              Đến <em>biên bản.</em>
            </h1>
            <p>
              Giữ trọn nội dung cuộc họp. Biến bản ghi âm thành lời chép có căn
              cứ và biên bản chỉn chu, trong một không gian thống nhất.
            </p>
            <div className="hero-actions">
              <Link className="marketing-button" to={appUrl}>
                Mở Minda <ArrowRight size={17} />
              </Link>
              <a className="marketing-text-link" href="#product-tour">
                Khám phá quy trình <ArrowUpRight size={17} />
              </a>
            </div>
            <div className="hero-assurance">
              <ShieldCheck size={16} /> Lưu trữ tại máy chủ triển khai của đơn
              vị
            </div>
          </div>
          <div className="hero-sculpture">
            <AmbientVisual kind="layers" />
            <div className="sculpture-caption">
              <span className="live-dot" /> Âm thanh · Căn cứ · Biên bản{" "}
              <span>01—03</span>
            </div>
          </div>
        </section>
        <Reveal className="product-reveal">
          <section
            id="product-tour"
            className="product-tour"
            aria-labelledby="tour-heading"
          >
            <div className="tour-heading">
              <div>
                <span className="marketing-kicker">
                  MỘT QUY TRÌNH LIỀN MẠCH
                </span>
                <h2 id="tour-heading">
                  Hiểu rõ từng lời.
                  <br />
                  Nắm chắc từng ý.
                </h2>
              </div>
              <p>
                Lắng nghe, đối chiếu và hoàn thiện tài liệu.
                <br />
                Mọi bước kết nối ngay trong Minda.
              </p>
            </div>
            <div className="product-window">
              <div className="product-window-bar">
                <div className="window-dots">
                  <i />
                  <i />
                  <i />
                </div>
                <span>Minda / Không gian cuộc họp</span>
                <span className="demo-label">
                  Giao diện thật · Dữ liệu minh họa
                </span>
              </div>
              <div
                className="product-tabs"
                role="tablist"
                aria-label="Khám phá giao diện Minda"
              >
                <button
                  role="tab"
                  id="tour-transcript"
                  tabIndex={tab === "transcript" ? 0 : -1}
                  aria-selected={tab === "transcript"}
                  aria-controls="tour-panel"
                  onClick={() => setTab("transcript")}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                      setTab("minutes");
                      document.getElementById("tour-minutes")?.focus();
                    }
                  }}
                >
                  <Headphones size={16} /> Rà soát lời chép
                </button>
                <button
                  role="tab"
                  id="tour-minutes"
                  tabIndex={tab === "minutes" ? 0 : -1}
                  aria-selected={tab === "minutes"}
                  aria-controls="tour-panel"
                  onClick={() => setTab("minutes")}
                  onKeyDown={(e) => {
                    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                      setTab("transcript");
                      document.getElementById("tour-transcript")?.focus();
                    }
                  }}
                >
                  <FileText size={16} /> Hoàn thiện biên bản
                </button>
              </div>
              <div
                id="tour-panel"
                tabIndex={0}
                role="tabpanel"
                aria-labelledby={`tour-${tab}`}
              >
                <img
                  src={`/product/${tab}.webp`}
                  alt={
                    tab === "transcript"
                      ? "Giao diện Minda thật: danh sách lời chép, nhãn người nói và tìm kiếm"
                      : "Giao diện Minda thật: nội dung biên bản cùng căn cứ đối chiếu"
                  }
                  width="1440"
                  height="1000"
                  loading="lazy"
                />
              </div>
            </div>
          </section>
        </Reveal>
        <section
          className="feature-stories"
          aria-label="Từ nguồn âm thanh đến tài liệu hoàn chỉnh"
        >
          {features.map(({ id, number, title, text, icon: Icon }) => (
            <Reveal key={id}>
              <article className="feature-story">
                <div className="feature-art">
                  <img
                    src={`/illustrations/${id}.webp`}
                    alt={
                      id === "signal"
                        ? "Minh họa các nguồn sóng âm hội tụ qua những lớp kính"
                        : id === "evidence"
                          ? "Minh họa các lớp thông tin được liên kết bằng căn cứ"
                          : "Minh họa tài liệu hoàn chỉnh với các lớp giấy và dải xanh"
                    }
                    width="1200"
                    height="900"
                    loading="lazy"
                  />
                </div>
                <div className="feature-copy">
                  <span className="feature-number">
                    {number} / QUY TRÌNH MINDA
                  </span>
                  <Icon size={25} strokeWidth={1.4} />
                  <h2>{title}</h2>
                  <p>{text}</p>
                  <Link to="/guide" className="marketing-text-link">
                    Tìm hiểu cách thực hiện <ArrowUpRight size={16} />
                  </Link>
                </div>
              </article>
            </Reveal>
          ))}
        </section>
        <Reveal>
          <section className="marketing-trust">
            <div>
              <ShieldCheck size={28} strokeWidth={1.3} />
              <span className="marketing-kicker">
                RÕ RÀNG ĐỂ AN TÂM SỬ DỤNG
              </span>
              <h2>
                Dữ liệu có nơi lưu.
                <br />
                Thông tin có căn cứ.
              </h2>
            </div>
            <div>
              <p>
                Minda vận hành trên máy chủ đơn vị triển khai. Quyền truy cập,
                phiên bản tài liệu và lịch sử xử lý được giữ rõ ràng trong từng
                bước.
              </p>
              <ul>
                <li>
                  <Check size={16} /> Tài nguyên được kiểm soát theo tài khoản
                </li>
                <li>
                  <Check size={16} /> Giữ lịch sử lời chép và biên bản
                </li>
                <li>
                  <Check size={16} /> Sao lưu và khôi phục có kiểm soát
                </li>
              </ul>
              <Link to="/data-policy" className="marketing-text-link">
                Tìm hiểu dữ liệu & quyền truy cập <ArrowRight size={16} />
              </Link>
            </div>
          </section>
        </Reveal>
        <Reveal>
          <section className="marketing-cta">
            <span className="marketing-kicker">
              BẮT ĐẦU TỪ CUỘC HỌP TIẾP THEO
            </span>
            <h2>
              Thêm tập trung cho cuộc họp.
              <br />
              Thêm rõ ràng cho công việc.
            </h2>
            <Link className="marketing-button" to={appUrl}>
              Mở không gian Minda <ArrowRight size={17} />
            </Link>
          </section>
        </Reveal>
      </div>
    </PublicLayout>
  );
}
