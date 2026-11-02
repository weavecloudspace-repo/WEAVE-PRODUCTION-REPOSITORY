import { useEffect } from "react";

import { cleanText } from "../../utils/academicDashboard";

const formatClassLabel = (card) =>
  [card?.class_name, card?.class_arm].filter(Boolean).join(" ") || "Not assigned";

const formatPosition = (card) => {
  if (card?.position === null || card?.position === undefined) return "--";
  return card?.position_out_of
    ? `${card.position} of ${card.position_out_of}`
    : String(card.position);
};

const formatPublishedDate = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(date);
};

function ReportCardPrintSheet({ card, onAfterPrint }) {
  useEffect(() => {
    if (!card) return undefined;

    const clearAfterPrint = () => onAfterPrint?.();
    window.addEventListener("afterprint", clearAfterPrint, { once: true });

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const root = document.querySelector(".report-card-print-root");
      const images = root ? [...root.querySelectorAll("img")] : [];
      await Promise.all(
        images.map((image) => {
          if (image.complete) return Promise.resolve();
          return new Promise((resolve) => {
            image.addEventListener("load", resolve, { once: true });
            image.addEventListener("error", resolve, { once: true });
          });
        }),
      );
      if (!cancelled) window.print();
    }, 80);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("afterprint", clearAfterPrint);
    };
  }, [card, onAfterPrint]);

  if (!card) return null;

  const schoolName = cleanText(card.school_name, "Weave School");
  const schoolLogo = card.school_logo_url || "/icons/weave-email-icon.png";
  const studentPhoto = card.student_passport_photo_url;
  const lines = Array.isArray(card.lines) ? card.lines : [];
  const componentHeaders = lines[0]?.components || [];

  return (
    <section className="report-card-print-root" aria-hidden="true">
      <style>
        {`
          .report-card-print-root { display: none; }
          @page { size: A4 portrait; margin: 10mm; }
          @media print {
            body * { visibility: hidden; }
            .report-card-print-root,
            .report-card-print-root * { visibility: visible; }
            .report-card-print-root {
              display: block;
              position: absolute;
              inset: 0;
              color: #172033;
              background: #ffffff;
              font-family: Arial, Helvetica, sans-serif;
              line-height: 1.35;
            }
            .rc-sheet { width: 100%; }
            .rc-header {
              display: grid;
              grid-template-columns: 82px 1fr auto;
              gap: 16px;
              align-items: center;
              border-bottom: 3px solid #1d4ed8;
              padding-bottom: 16px;
            }
            .rc-school-logo {
              width: 76px;
              height: 76px;
              object-fit: contain;
              border: 1px solid #dbe4f0;
              border-radius: 14px;
              padding: 7px;
            }
            .rc-school-name { margin: 0; color: #0f2454; font-size: 25px; line-height: 1.12; }
            .rc-school-meta { margin: 4px 0 0; color: #667085; font-size: 10px; }
            .rc-title { text-align: right; }
            .rc-title h2 { margin: 0; font-size: 17px; letter-spacing: .08em; text-transform: uppercase; }
            .rc-title p { margin: 5px 0 0; color: #667085; font-size: 10px; }
            .rc-student {
              display: grid;
              grid-template-columns: 86px minmax(0, 1fr);
              gap: 18px;
              margin-top: 18px;
              border: 1px solid #cbd5e1;
              border-radius: 14px;
              background: #f8fafc;
              padding: 16px;
              break-inside: avoid;
            }
            .rc-student-photo {
              width: 82px;
              height: 98px;
              object-fit: cover;
              object-position: center;
              border: 1px solid #cbd5e1;
              border-radius: 9px;
              background: #ffffff;
            }
            .rc-photo-placeholder {
              box-sizing: border-box;
            }
            .rc-student-name { margin: 0 0 8px; font-size: 19px; }
            .rc-meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
            .rc-field { border-left: 3px solid #bfdbfe; padding-left: 8px; min-width: 0; }
            .rc-field span,
            .rc-metric span {
              display: block;
              color: #667085;
              font-size: 8px;
              font-weight: 700;
              letter-spacing: .06em;
              text-transform: uppercase;
            }
            .rc-field strong { display: block; margin-top: 3px; font-size: 10px; overflow-wrap: anywhere; }
            .rc-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin: 14px 0; break-inside: avoid; }
            .rc-metric { border: 1px solid #bfdbfe; border-radius: 10px; background: #eff6ff; padding: 9px; text-align: center; }
            .rc-metric strong { display: block; margin-top: 4px; color: #0f2454; font-size: 15px; }
            .rc-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9px; }
            .rc-table thead { display: table-header-group; }
            .rc-table tr { break-inside: avoid; page-break-inside: avoid; }
            .rc-table th,
            .rc-table td { border: 1px solid #cbd5e1; padding: 6px 5px; text-align: center; vertical-align: middle; overflow-wrap: anywhere; }
            .rc-table th { background: #eaf1ff; color: #173a77; font-size: 7px; letter-spacing: .04em; text-transform: uppercase; }
            .rc-table .left { text-align: left; }
            .rc-table .strong { font-weight: 700; }
            .rc-comments { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px; break-inside: avoid; }
            .rc-comment { min-height: 82px; border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px; }
            .rc-comment h3 { margin: 0 0 6px; color: #173a77; font-size: 9px; letter-spacing: .05em; text-transform: uppercase; }
            .rc-comment p { margin: 0; font-size: 9px; white-space: pre-wrap; }
            .rc-signatures { display: grid; grid-template-columns: 1fr 1fr; gap: 64px; margin-top: 30px; break-inside: avoid; }
            .rc-signature { border-top: 1px solid #475569; padding-top: 5px; color: #667085; font-size: 9px; text-align: center; }
            .rc-footer { display: flex; justify-content: space-between; gap: 14px; margin-top: 17px; border-top: 1px solid #dbe4f0; padding-top: 8px; color: #667085; font-size: 8px; }
          }
        `}
      </style>

      <main className="rc-sheet">
        <header className="rc-header">
          <img className="rc-school-logo" src={schoolLogo} alt="School logo" />
          <div>
            <h1 className="rc-school-name">{schoolName}</h1>
            {card.school_address ? <p className="rc-school-meta">{card.school_address}</p> : null}
            {(card.school_phone || card.school_email) ? (
              <p className="rc-school-meta">
                {[card.school_phone, card.school_email].filter(Boolean).join(" · ")}
              </p>
            ) : null}
          </div>
          <div className="rc-title">
            <h2>Termly Academic Report</h2>
            <p>
              {cleanText(card.academic_session_name)} · {cleanText(card.academic_term_name)}
            </p>
          </div>
        </header>

        <section className="rc-student">
          {studentPhoto ? (
            <img className="rc-student-photo" src={studentPhoto} alt="Student passport" />
          ) : (
            <div
              className="rc-student-photo rc-photo-placeholder"
              role="img"
              aria-label="Student photo not provided"
            />
          )}
          <div>
            <h2 className="rc-student-name">
              {cleanText(card.student_name, card.admission_number || "Student")}
            </h2>
            <div className="rc-meta">
              <PrintField label="Admission number" value={cleanText(card.admission_number, "Not assigned")} />
              <PrintField label="Class" value={formatClassLabel(card)} />
              <PrintField label="Session" value={cleanText(card.academic_session_name)} />
              <PrintField label="Term" value={cleanText(card.academic_term_name)} />
              <PrintField label="Status" value={cleanText(card.status)} />
              <PrintField label="Published" value={formatPublishedDate(card.published_at)} />
              <PrintField label="Version" value={cleanText(card.version, "1")} />
              <PrintField label="Report ID" value={String(card.id || "").slice(0, 8).toUpperCase()} />
            </div>
          </div>
        </section>

        <section className="rc-summary">
          <PrintMetric label="Total score" value={cleanText(card.total_score)} />
          <PrintMetric label="Average" value={cleanText(card.average_score)} />
          <PrintMetric label="Position" value={formatPosition(card)} />
          <PrintMetric label="Subjects" value={lines.length} />
          <PrintMetric label="Term" value={cleanText(card.academic_term_name)} />
        </section>

        <table className="rc-table">
          <thead>
            <tr>
              <th>Subject</th>
              <th>Code</th>
              {componentHeaders.map((component) => <th key={component.assessment_component_id}>{component.name}</th>)}
              <th>Total</th>
              <th>Grade</th>
              <th>Remark</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr key={line.id || line.subject_id}>
                <td className="left">{cleanText(line.subject_name)}</td>
                <td>{cleanText(line.subject_code)}</td>
                {componentHeaders.map((header) => {
                  const component = (line.components || []).find((item) => item.assessment_component_id === header.assessment_component_id);
                  return <td key={header.assessment_component_id}>{cleanText(component?.score)}</td>;
                })}
                <td className="strong">{cleanText(line.total_score)}</td>
                <td>{cleanText(line.grade)}</td>
                <td className="left">{cleanText(line.remark, "")}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <section className="rc-comments">
          <PrintComment
            title="Class teacher's comment"
            value={cleanText(card.class_teacher_comment, "No class teacher comment provided.")}
          />
          <PrintComment
            title="Principal's comment"
            value={cleanText(card.principal_comment, "No principal comment provided.")}
          />
        </section>

        <section className="rc-signatures">
          <div className="rc-signature">Class teacher signature</div>
          <div className="rc-signature">Principal signature</div>
        </section>

        <footer className="rc-footer">
          <span>{schoolName}</span>
          <span>Generated securely by Weave · Report {card.id}</span>
        </footer>
      </main>
    </section>
  );
}

function PrintField({ label, value }) {
  return (
    <div className="rc-field">
      <span>{label}</span>
      <strong>{value || "--"}</strong>
    </div>
  );
}

function PrintMetric({ label, value }) {
  return (
    <div className="rc-metric">
      <span>{label}</span>
      <strong>{value ?? "--"}</strong>
    </div>
  );
}

function PrintComment({ title, value }) {
  return (
    <article className="rc-comment">
      <h3>{title}</h3>
      <p>{value}</p>
    </article>
  );
}

export default ReportCardPrintSheet;
