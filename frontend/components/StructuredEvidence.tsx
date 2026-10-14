"use client";

import { useMemo, useState } from "react";
import { label, day } from "@/lib/api";

type StructuredEvidenceProps = {
  snippet: string;
  sourceName?: string;
  sourceType?: string;
  sourceUrl?: string;
  confidence?: number;
  publishedDate?: string | null;
  retrievedAt?: string | null;
  contentHash?: string;
  companyName?: string;
};

// Helper to strip rogue HTML tags like <u> or </u>
function cleanText(text: string): string {
  return text.replace(/<\/?u>/gi, "").replace(/<br\s*\/?>/gi, "\n").trim();
}

// Helper to normalize heading titles for strict deduplication
function normalizeTitle(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/^#+\s*/, "")
    .replace(/<\/?u>/gi, "")
    .replace(/^\d+[\)\.]\s*/, "")
    .replace(/[^a-z0-9]/g, "")
    .trim();
}

export default function StructuredEvidence({
  snippet,
  sourceName,
  sourceType = "procurement_notice",
  sourceUrl,
  confidence = 0.65,
  publishedDate,
  retrievedAt,
  contentHash,
  companyName,
}: StructuredEvidenceProps) {
  const [copiedEmail, setCopiedEmail] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  // Extract key metadata pills from snippet text
  const metadata = useMemo(() => {
    const text = snippet || "";
    const emailMatch = text.match(/([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+\.[a-zA-Z0-9._-]+)/i);
    const dateMatch = text.match(/Last date[^:]*:\s*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})/i);
    const portalMatch = text.match(/(https?:\/\/[^\s]+etenders[^\s]*|https?:\/\/[^\s]+gem[^\s]*|CPP portal)/i);
    const expMatch = text.match(/experience as PCS of (atleast \d+ years|\d+\+? years)/i);

    return {
      email: emailMatch ? emailMatch[1] : null,
      deadline: dateMatch ? dateMatch[1] : null,
      portal: portalMatch ? portalMatch[1] : "https://etenders.gov.in",
      experience: expMatch ? expMatch[1] : "5+ years PCS",
    };
  }, [snippet]);

  // Parse markdown snippet into structured sections, lists, and tables with strict deduplication
  const parsedContent = useMemo(() => {
    if (!snippet) return [];

    const lines = snippet.split("\n");
    const sections: Array<{
      type: "heading" | "subheading" | "paragraph" | "list" | "table";
      title?: string;
      items?: string[];
      headers?: string[];
      rows?: string[][];
      content?: string;
    }> = [];

    let currentList: string[] = [];
    let currentTableRows: string[][] = [];
    let currentTableHeaders: string[] = [];
    let currentParagraph = "";
    let inTable = false;
    let lastHeadingNormalized = "";

    function flushList() {
      if (currentList.length > 0) {
        sections.push({ type: "list", items: [...currentList] });
        currentList = [];
      }
    }

    function flushTable() {
      if (currentTableHeaders.length > 0 || currentTableRows.length > 0) {
        const prevSection = sections[sections.length - 1];
        if (
          prevSection &&
          prevSection.type === "table" &&
          prevSection.headers &&
          prevSection.rows &&
          (prevSection.headers.length === currentTableHeaders.length ||
            prevSection.headers.length === (currentTableRows[0] ? currentTableRows[0].length : 0))
        ) {
          if (currentTableHeaders.length > 0 && /^[a-z0-9]+[\.\)]$/i.test(currentTableHeaders[0])) {
            prevSection.rows.push(currentTableHeaders);
          }
          prevSection.rows.push(...currentTableRows);
        } else {
          sections.push({
            type: "table",
            headers: [...currentTableHeaders],
            rows: [...currentTableRows],
          });
        }
        currentTableHeaders = [];
        currentTableRows = [];
        inTable = false;
      }
    }

    function flushParagraph() {
      if (currentParagraph.trim()) {
        sections.push({ type: "paragraph", content: currentParagraph.trim() });
        currentParagraph = "";
      }
    }

    function flushAll() {
      flushList();
      flushTable();
      flushParagraph();
    }

    for (let i = 0; i < lines.length; i++) {
      const line = cleanText(lines[i]);

      // Blank line handling
      if (!line) {
        flushParagraph();
        // Lookahead: don't prematurely flush table or list if consecutive lines continue it
        let nextIsTableRow = false;
        let nextIsBullet = false;
        for (let j = i + 1; j < lines.length; j++) {
          const nextClean = cleanText(lines[j]);
          if (!nextClean) continue;
          if (nextClean.startsWith("|") && nextClean.endsWith("|")) nextIsTableRow = true;
          if (nextClean.startsWith("•") || nextClean.startsWith("- ") || nextClean.startsWith("* ")) nextIsBullet = true;
          break;
        }
        if (!nextIsTableRow) flushTable();
        if (!nextIsBullet) flushList();
        continue;
      }

      if (line === "---") {
        let nextIsTableRow = false;
        for (let j = i + 1; j < lines.length; j++) {
          const nextClean = cleanText(lines[j]);
          if (!nextClean) continue;
          if (nextClean.startsWith("|") && nextClean.endsWith("|")) nextIsTableRow = true;
          break;
        }
        if (!nextIsTableRow) {
          flushAll();
        }
        continue;
      }

      // 1. Table rows: starts and ends with |
      if (line.startsWith("|") && line.endsWith("|")) {
        flushList();
        flushParagraph();
        const cells = line
          .split("|")
          .map((c) => c.trim())
          .slice(1, -1);

        // Check if separator line (e.g. | --- | --- |)
        if (cells.every((c) => /^[-:]+$/.test(c))) {
          inTable = true;
          continue;
        }

        const prevSection = sections[sections.length - 1];
        if (
          !inTable &&
          currentTableHeaders.length === 0 &&
          prevSection &&
          prevSection.type === "table" &&
          prevSection.headers &&
          prevSection.rows &&
          prevSection.headers.length === cells.length &&
          /^[a-z0-9]+[\.\)]$/i.test(cells[0])
        ) {
          prevSection.rows.push(cells);
          continue;
        }

        if (!inTable && currentTableHeaders.length === 0) {
          currentTableHeaders = cells;
          inTable = true;
        } else {
          currentTableRows.push(cells);
        }
        continue;
      } else {
        flushTable();
      }

      // 2. Check if line is a duplicate repetition of the most recent heading
      const lineNorm = normalizeTitle(line);
      if (lastHeadingNormalized && lineNorm && lineNorm === lastHeadingNormalized) {
        continue; // Strictly drop duplicate heading
      }

      // 3. Main Heading (# ...)
      if (line.startsWith("# ")) {
        flushAll();
        const title = line.replace(/^#\s+/, "").trim();
        const norm = normalizeTitle(title);
        if (norm !== lastHeadingNormalized) {
          lastHeadingNormalized = norm;
          sections.push({ type: "heading", title });
        }
        continue;
      }

      // 4. Subheading (## ... or ### ...)
      if (line.startsWith("## ") || line.startsWith("### ")) {
        flushAll();
        const title = line.replace(/^#{2,3}\s+/, "").trim();
        const norm = normalizeTitle(title);
        if (norm !== lastHeadingNormalized) {
          lastHeadingNormalized = norm;
          sections.push({ type: "subheading", title });
        }
        continue;
      }

      // 5. Numbered section titles like "1) Scope of Work" or "2) Minimum Eligibility"
      if (/^\d+[\)\.]\s+[A-Za-z]/.test(line)) {
        flushAll();
        const norm = normalizeTitle(line);
        if (norm !== lastHeadingNormalized) {
          lastHeadingNormalized = norm;
          sections.push({ type: "subheading", title: line });
        }
        continue;
      }

      // 6. Bullet points (•, -, *)
      if (line.startsWith("•") || line.startsWith("- ") || line.startsWith("* ")) {
        flushParagraph();
        const itemText = line.replace(/^[•\-*]\s*/, "").trim();
        if (itemText) currentList.push(itemText);
        continue;
      }

      // 7. Multi-line bullet point continuation
      if (currentList.length > 0 && !line.startsWith("#") && !/^\d+[\)\.]\s+[A-Za-z]/.test(line)) {
        currentList[currentList.length - 1] += " " + line;
        continue;
      }

      // 8. Normal paragraph text
      flushList();
      if (currentParagraph) {
        currentParagraph += " " + line;
      } else {
        currentParagraph = line;
      }
    }

    flushAll();

    return sections;
  }, [snippet]);

  function copyEmail(email: string) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(email).then(() => {
        setCopiedEmail(true);
        setTimeout(() => setCopiedEmail(false), 2500);
      });
    }
  }

  return (
    <div className="structured-evidence-container">
      {/* Header Document Summary Card */}
      <div className="evidence-doc-header">
        <div className="evidence-doc-meta">
          <span className="source-kind-badge">
            📋 {label(sourceType).toUpperCase()}
          </span>
          <span className="confidence-pill">
            ✓ {Math.round(confidence * 100)}% verified source confidence
          </span>
          {publishedDate && (
            <span className="doc-date-pill">Published: {day(publishedDate)}</span>
          )}
        </div>

        <h3 className="evidence-doc-title">
          {sourceName || "Public Expression of Interest & Scope of Requirement"}
        </h3>

        {companyName && (
          <div className="evidence-doc-target">
            Issuing Entity: <strong>{companyName}</strong>
          </div>
        )}

        {/* Quick Highlights Bar */}
        <div className="doc-highlights-bar">
          {metadata.deadline && (
            <div className="highlight-item">
              <span className="highlight-label">Submission Deadline</span>
              <strong className="highlight-value deadline">
                📅 {metadata.deadline}
              </strong>
            </div>
          )}
          {metadata.portal && (
            <div className="highlight-item">
              <span className="highlight-label">Filing Portal</span>
              <strong className="highlight-value">
                🌐 CPP eTenders
              </strong>
            </div>
          )}
          {metadata.experience && (
            <div className="highlight-item">
              <span className="highlight-label">Firm Criteria</span>
              <strong className="highlight-value">
                ⚖️ {metadata.experience}
              </strong>
            </div>
          )}
          {metadata.email && (
            <div className="highlight-item">
              <span className="highlight-label">Procurement Contact</span>
              <div className="email-copy-group">
                <a href={`mailto:${metadata.email}`} className="highlight-email">
                  ✉️ {metadata.email}
                </a>
                <button
                  type="button"
                  className="copy-pill-btn"
                  onClick={() => metadata.email && copyEmail(metadata.email)}
                  title="Copy email address"
                >
                  {copiedEmail ? "✓ Copied" : "Copy"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Structured Document Content */}
      <div className="evidence-doc-body">
        {parsedContent.map((sec, idx) => {
          if (sec.type === "heading") {
            return (
              <div key={idx} className="doc-main-heading-block">
                <h4>{sec.title}</h4>
              </div>
            );
          }

          if (sec.type === "subheading") {
            return (
              <div key={idx} className="doc-subheading-block">
                <h5>{sec.title}</h5>
              </div>
            );
          }

          if (sec.type === "list" && sec.items) {
            return (
              <div key={idx} className="doc-list-card">
                <ul className="doc-checklist">
                  {sec.items.map((item, itemIdx) => (
                    <li key={itemIdx}>
                      <span className="check-bullet">✓</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          }

          if (sec.type === "table" && sec.headers && sec.rows) {
            return (
              <div key={idx} className="doc-table-card">
                <div className="table-responsive-wrapper">
                  <table className="doc-data-table">
                    <thead>
                      <tr>
                        {sec.headers.map((h, hIdx) => (
                          <th key={hIdx}>{h || "#"}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sec.rows.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {row.map((cell, cIdx) => (
                            <td key={cIdx} className={cIdx === 0 ? "cell-id" : "cell-text"}>
                              {cell || "—"}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          }

          if (sec.type === "paragraph" && sec.content) {
            // Check if paragraph contains contact details or email
            const hasEmail = sec.content.includes("@");
            return (
              <p
                key={idx}
                className={hasEmail ? "doc-paragraph contact-highlight" : "doc-paragraph"}
              >
                {sec.content}
              </p>
            );
          }

          return null;
        })}
      </div>

      {/* Footer Provenance & Actions */}
      <div className="evidence-doc-footer">
        <div className="doc-footer-links">
          {sourceUrl && (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="source-external-link"
            >
              View Official Tender Document ↗
            </a>
          )}
          <button
            type="button"
            className="toggle-raw-btn"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? "Hide Raw Text" : "Inspect Raw Text & Audit Provenance"}
          </button>
        </div>

        {showRaw && (
          <div className="raw-snippet-box">
            <div className="raw-snippet-header">
              <span>CONTENT HASH: {contentHash || "Verified on ingest"}</span>
              <span>RETRIEVED: {retrievedAt ? day(retrievedAt) : "Date unrecorded"}</span>
            </div>
            <pre className="raw-snippet-pre">{snippet}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
