import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import './App.css'

const API = import.meta.env.VITE_API_BASE ?? ''
const ALLOWED = ['scribd.com', 'drive.google.com', 'docs.google.com']
const SOURCE_EXTS =
  'docx, doc, xlsx, xls, pptx, ppt, odt, ods, odp, rtf, txt, csv, pdf, png, jpg, jpeg, webp, bmp, tiff, html'
const TARGETS = ['pdf', 'docx', 'txt', 'html', 'xlsx', 'csv']
const LOGOUT_EVENT = 'elena:logout'

type View = 'launcher' | 'form' | 'settings' | 'processing' | 'result'
type Tool = 'scan' | 'convert' | 'protect' | 'library'

interface JobStatus {
  job_id: string
  status: string
  ok: boolean | null
  brief: string[]
  error: string | null
  kind?: string
  target?: string
}

interface User {
  id: number
  email: string
  username: string
  full_name: string
  created_at: number
}

function getStoredUser(): User | null {
  try {
    return JSON.parse(localStorage.getItem('elena_user') ?? 'null')
  } catch {
    return null
  }
}

function clearSession() {
  localStorage.removeItem('elena_token')
  localStorage.removeItem('elena_user')
}

/**
 * fetch wrapper that injects X-Auth-Token and logs out on 401. Callers handle
 * the thrown error; the app-level listener flips to the auth screen.
 */
async function api(path: string, opts: RequestInit = {}): Promise<Response> {
  const headers = new Headers(opts.headers)
  const token = localStorage.getItem('elena_token')
  if (token) headers.set('X-Auth-Token', token)
  const res = await fetch(`${API}${path}`, { ...opts, headers })
  if (res.status === 401) {
    clearSession()
    window.dispatchEvent(new Event(LOGOUT_EVENT))
    throw new Error('Chưa đăng nhập')
  }
  return res
}

/** Auth-less fetch for /auth/* endpoints. */
async function authApi(path: string, opts: RequestInit = {}): Promise<Response> {
  return fetch(`${API}${path}`, opts)
}

async function downloadFile(path: string, filename?: string) {
  const res = await api(path)
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new Error(data?.error ?? 'Tải file thất bại')
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || ''
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function deriveKy(): string {
  const m = new Date().getMonth() + 1
  return m >= 8 || m <= 1 ? 'HK1' : 'HK2'
}

function checkLink(link: string): string | null {
  if (!/^https?:\/\//.test(link)) return 'Link phải bắt đầu bằng http(s)://'
  try {
    const host = new URL(link).hostname.toLowerCase()
    if (!ALLOWED.some((d) => host === d || host.endsWith('.' + d)))
      return 'Domain chưa được hỗ trợ (chỉ: scribd.com, drive.google.com, docs.google.com)'
    if (!/^(scribd\.com|www\.scribd\.com)/.test(host) && !/^(drive|docs)\.google\.com/.test(host))
      return 'Domain chưa được hỗ trợ'
  } catch {
    return 'Link không hợp lệ'
  }
  return null
}

function SandDrift() {
  return (
    <div className="sand" aria-hidden="true">
      {Array.from({ length: 26 }, (_, i) => (
        <span
          key={i}
          style={{
            left: `${(i * 37 + 11) % 100}%`,
            animationDelay: `${(i * 0.73) % 6}s`,
            animationDuration: `${4 + ((i * 1.37) % 5)}s`,
            opacity: 0.18 + ((i * 13) % 40) / 100,
            scale: `${0.5 + ((i * 7) % 10) / 10}`,
          }}
        />
      ))}
    </div>
  )
}

function WaterLine({ done }: { done: boolean }) {
  return (
    <div className={`water ${done ? 'water-done' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 600 24" preserveAspectRatio="none">
        <path
          className="water-path"
          d="M0 14 C 60 4, 120 22, 180 12 S 300 2, 360 13 S 480 22, 600 10"
          fill="none"
        />
      </svg>
      <span className="water-tip">{done ? '●' : '○'}</span>
    </div>
  )
}

const KYS = ['HK1', 'HK2'] as const

function ScanIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M14 4h14l8 8v32H14z" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M28 4v8h8" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
      <line x1="19" y1="22" x2="33" y2="22" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="19" y1="28" x2="33" y2="28" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="19" y1="34" x2="27" y2="34" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function ConvertIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M8 16h26l-7-7" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M40 32H14l7 7" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 11v6h6" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M40 37v-6h-6" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ProtectIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 4l16 6v12c0 10.5-6.6 17.6-16 22C14.6 39.6 8 32.5 8 22V10z" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M18 24l4 4 8-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function LibraryIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M8 14l16-6 16 6v22L24 42 8 36z" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M24 8v34" stroke="currentColor" strokeWidth="2.5" />
      <path d="M16 17v11M32 17v11" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg className="tool-svg" viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 32a8 8 0 1 0 0-16 8 8 0 0 0 0 16z" fill="none" stroke="currentColor" strokeWidth="2.5" />
      <path
        d="M38 28a14.8 14.8 0 0 0 .2-4 14.8 14.8 0 0 0-.2-4l4-3.1-4-7-4.7 1.8a15 15 0 0 0-3.5-2L29 5h-8l-.8 4.7a15 15 0 0 0-3.5 2l-4.7-1.8-4 7 4 3.1a14.8 14.8 0 0 0 0 8l-4 3.1 4 7 4.7-1.8a15 15 0 0 0 3.5 2L21 39h8l.8-4.7a15 15 0 0 0 3.5-2l4.7 1.8 4-7z"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

interface ToolCardProps {
  title: string
  desc: string
  icon: ReactNode
  onClick: () => void
}

function ToolCard({ title, desc, icon, onClick }: ToolCardProps) {
  return (
    <button type="button" className="tool-card" onClick={onClick}>
      {icon}
      <span className="tool-title">{title}</span>
      <span className="tool-desc">{desc}</span>
    </button>
  )
}

const TARGET_OPTIONS = TARGETS.map((t) => ({ value: t, label: `Đích: .${t}${t === 'pdf' ? ' (mặc định)' : ''}` }))

interface SelectOption {
  value: string
  label: string
}

interface FieldSelectProps {
  options: SelectOption[]
  value: string
  onChange: (v: string) => void
  ariaLabel: string
  wrapClass?: string
}

function FieldSelect({ options, value, onChange, ariaLabel, wrapClass }: FieldSelectProps) {
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const wrap = useRef<HTMLDivElement>(null)
  const idx = options.findIndex((o) => o.value === value)

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const pick = (v: string) => {
    onChange(v)
    setOpen(false)
  }

  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Escape') {
      setOpen(false)
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        setHi(idx >= 0 ? idx : 0)
        setOpen(true)
      } else {
        setHi((h) => (e.key === 'ArrowDown' ? (h + 1) % options.length : (h - 1 + options.length) % options.length))
      }
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open) pick(options[hi].value)
      else setOpen(true)
    }
  }

  const current = options.find((o) => o.value === value)

  return (
    <div className={`ky ${wrapClass ?? ''}`} ref={wrap}>
      <button
        type="button"
        className={`ky-trigger field ${open ? 'ky-open' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => {
          setOpen((o) => !o)
          setHi(options.findIndex((o) => o.value === value))
        }}
        onKeyDown={onKey}
      >
        <span>{current?.label ?? value}</span>
        <span className="ky-carat" aria-hidden="true">
          ▾
        </span>
      </button>
      {open && (
        <div className="ky-menu" role="listbox" aria-label={ariaLabel}>
          {options.map((o, i) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === value}
              className={`ky-item ${o.value === value ? 'ky-selected' : ''} ${i === hi ? 'ky-hi' : ''}`}
              onMouseEnter={() => setHi(i)}
              onClick={() => pick(o.value)}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

interface HitRow {
  page: number
  rect: number[]
  text: string
}

interface PreviewRes {
  pages: number
  hits: HitRow[]
  term_missed: string[]
}

const PROTECT_STEPS = ['Chọn file', 'Tùy chọn bảo vệ', 'Xem vùng xoá', 'Kết quả']

function ProtectWizard({
  submitProtect,
}: {
  submitProtect: (file: File, config: unknown) => Promise<string | null>
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState(1)
  const [file, setFile] = useState<File | null>(null)

  const [pwEnabled, setPwEnabled] = useState(false)
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')

  const [permEnabled, setPermEnabled] = useState(false)
  const [blockPrint, setBlockPrint] = useState(true)
  const [blockCopy, setBlockCopy] = useState(true)
  const [blockModify, setBlockModify] = useState(true)
  const [blockAnnotate, setBlockAnnotate] = useState(true)

  const [wmEnabled, setWmEnabled] = useState(false)
  const [wmText, setWmText] = useState('CONFIDENTIAL')
  const [wmSuffix, setWmSuffix] = useState('')

  const [sanitize, setSanitize] = useState(false)

  const [redactEnabled, setRedactEnabled] = useState(false)
  const [termsText, setTermsText] = useState('')

  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<PreviewRes | null>(null)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const termsList = [...new Set(termsText.split('\n').map((t) => t.trim()).filter(Boolean))]

  const runPreview = async () => {
    if (!file) return
    setPreviewing(true)
    setErr(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('terms', termsList.join('\n'))
      const res = await api('/protect/preview', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) {
        setErr(data.error ?? 'Lỗi máy chủ')
        return
      }
      const hits: HitRow[] = data.hits ?? []
      setPreview({ pages: data.pages, hits, term_missed: data.term_missed ?? [] })
      setChecked(new Set(hits.map((_, i) => i)))
    } catch {
      setErr('Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    } finally {
      setPreviewing(false)
    }
  }

  const toggle = (i: number) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  const buildConfig = () => {
    const hits = preview?.hits ?? []
    const regions = hits.filter((_, i) => checked.has(i)).map((h) => ({ page: h.page, rect: h.rect }))
    const redactTerms = redactEnabled && checked.size > 0 ? termsList : []
    return {
      password_enabled: pwEnabled,
      user_password: pwEnabled ? pw : '',
      owner_password: pwEnabled ? pw : '',
      restrict_enabled: permEnabled,
      allow_print: !blockPrint,
      allow_modify: !blockModify,
      allow_copy: !blockCopy,
      allow_annotate: !blockAnnotate,
      watermark_enabled: wmEnabled,
      watermark_text: wmText.trim() || 'CONFIDENTIAL',
      watermark_suffix: wmSuffix.trim() || undefined,
      sanitize_enabled: sanitize,
      redact_enabled: redactEnabled,
      redact_terms: redactTerms,
      redact_regions: regions,
    }
  }

  const next = async () => {
    setErr(null)
    if (step === 1) {
      if (!file) return setErr('Chọn file PDF cần bảo vệ')
      if (!/\.pdf$/i.test(file.name)) return setErr('Chỉ chọn file PDF (.pdf)')
      setStep(2)
    } else if (step === 2) {
      if (pwEnabled) {
        if (!pw) return setErr('Nhập mật khẩu mở file')
        if (pw !== pw2) return setErr('Mật khẩu không khớp')
      }
      if (redactEnabled && termsList.length === 0)
        return setErr('Nhập ít nhất một từ khoá cần xoá (mỗi từ một dòng)')
      setStep(redactEnabled ? 3 : 4)
    } else if (step === 3) {
      if (!preview) return await runPreview()
      if (checked.size === 0) setErr('Bạn chưa chọn vùng nào — sẽ không xoá gì')
      setStep(4)
    } else {
      if (!file) return
      setBusy(true)
      const msg = await submitProtect(file, buildConfig())
      if (msg) {
        setErr(msg)
        setBusy(false)
      }
    }
  }

  const back = () => {
    setErr(null)
    setStep((s) => Math.max(1, s - 1))
  }

  const ctaLabel =
    step === 1
      ? 'Tiếp tục'
      : step === 2
        ? 'Tiếp tục'
        : step === 3
          ? preview
            ? 'Xoá các vùng đã chọn'
            : 'Xem các vùng cần xoá'
          : 'Bảo vệ PDF'

  const perms: Array<[string, boolean, (v: boolean) => void]> = [
    ['Chặn in', blockPrint, setBlockPrint],
    ['Chặn sao chép', blockCopy, setBlockCopy],
    ['Chặn chỉnh sửa', blockModify, setBlockModify],
    ['Chặn chú thích', blockAnnotate, setBlockAnnotate],
  ]

  return (
    <>
      <p className="eyebrow">Bảo vệ PDF · quyền riêng tư</p>
      <h1>Giữ tài liệu của bạn an toàn trước khi chia sẻ.</h1>
      <p className="sub">
        Đặt mật khẩu, chặn các thao tác không mong muốn, thêm watermark, làm sạch metadata và xoá
        vĩnh viễn thông tin nhạy cảm (số CCCD, số điện thoại, mã số thuế…).
      </p>

      <div className="stepper" aria-label="Các bước">
        {PROTECT_STEPS.map((label, i) => {
          const n = i + 1
          return (
            <span key={label} className={`step ${step === n ? 'active' : ''} ${step > n ? 'done' : ''}`}>
              {n}. {label}
            </span>
          )
        })}
      </div>

      {step === 1 && (
        <>
          <input
            ref={fileRef}
            type="file"
            className="hidden-file"
            accept=".pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div
            className="dropzone"
            role="button"
            tabIndex={0}
            onClick={() => fileRef.current?.click()}
            onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
          >
            {file ? (
              <span className="fname">{file.name}</span>
            ) : (
              <span>
                Chọn file PDF để bảo vệ
                <br />
                <small>Chỉ nhận file .pdf</small>
              </span>
            )}
          </div>
        </>
      )}

      {step === 2 && (
        <div className="protect-opts">
          <div className="protect-opt">
            <label className="protect-opt-head">
              <input type="checkbox" checked={pwEnabled} onChange={(e) => setPwEnabled(e.target.checked)} />
              <span>Đặt mật khẩu mở file</span>
            </label>
            {pwEnabled && (
              <div className="protect-opt-body">
                <input
                  className="field"
                  type="password"
                  placeholder="Mật khẩu mở file"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                />
                <input
                  className="field"
                  type="password"
                  placeholder="Nhập lại mật khẩu"
                  value={pw2}
                  onChange={(e) => setPw2(e.target.value)}
                />
              </div>
            )}
          </div>

          <div className="protect-opt">
            <label className="protect-opt-head">
              <input type="checkbox" checked={permEnabled} onChange={(e) => setPermEnabled(e.target.checked)} />
              <span>Chặn in / sao chép / chỉnh sửa</span>
            </label>
            {permEnabled && (
              <div className="protect-opt-body perms">
                {perms.map(([label, val, setter]) => (
                  <label key={label} className="perm">
                    <input type="checkbox" checked={val} onChange={(e) => setter(e.target.checked)} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="protect-opt">
            <label className="protect-opt-head">
              <input type="checkbox" checked={wmEnabled} onChange={(e) => setWmEnabled(e.target.checked)} />
              <span>Thêm watermark</span>
            </label>
            {wmEnabled && (
              <div className="protect-opt-body">
                <input
                  className="field"
                  placeholder="Nội dung watermark (mặc định: CONFIDENTIAL)"
                  value={wmText}
                  onChange={(e) => setWmText(e.target.value)}
                />
                <input
                  className="field"
                  placeholder="Hậu tố (vd: email người nhận)"
                  value={wmSuffix}
                  onChange={(e) => setWmSuffix(e.target.value)}
                />
              </div>
            )}
          </div>

          <div className="protect-opt">
            <label className="protect-opt-head">
              <input type="checkbox" checked={sanitize} onChange={(e) => setSanitize(e.target.checked)} />
              <span>Làm sạch metadata</span>
            </label>
            <p className="opt-hint">Xoá thông tin tác giả, XMP và JavaScript nhúng trong file.</p>
          </div>

          <div className="protect-opt">
            <label className="protect-opt-head">
              <input type="checkbox" checked={redactEnabled} onChange={(e) => setRedactEnabled(e.target.checked)} />
              <span>Xoá thông tin nhạy cảm (Redact)</span>
            </label>
            {redactEnabled && (
              <div className="protect-opt-body">
                <textarea
                  className="field"
                  rows={4}
                  placeholder={'Một từ khoá mỗi dòng, vd:\n001234567890\n0909123456\n0312345678'}
                  value={termsText}
                  onChange={(e) => setTermsText(e.target.value)}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {step === 3 && (
        <>
          {!preview ? (
            <>
              <p className="sub">
                Từ khoá cần xoá ({termsList.length}): {termsList.join(', ')}
              </p>
              {err && <p className="error">{err}</p>}
            </>
          ) : (
            <>
              {preview.hits.length > 0 ? (
                <>
                  <p className="sub">
                    Tìm thấy {preview.hits.length} vùng trên {preview.pages} trang. Bỏ chọn vùng bạn
                    muốn giữ lại.
                  </p>
                  <ul className="hit-list">
                    {preview.hits.map((h, i) => (
                      <li key={i}>
                        <label>
                          <input type="checkbox" checked={checked.has(i)} onChange={() => toggle(i)} />
                          <span className="hit-page">Trang {h.page + 1}</span>
                          <code className="hit-text">{h.text}</code>
                          <span className="hit-rect">
                            ({Math.round(h.rect[0])},{Math.round(h.rect[1])})
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                  {checked.size === 0 && (
                    <p className="warn">Bạn chưa chọn vùng nào — sẽ không xoá gì.</p>
                  )}
                </>
              ) : (
                <p className="warn">Không tìm thấy từ khoá nào trong PDF.</p>
              )}
              {preview.term_missed.length > 0 && (
                <p className="warn">Cảnh báo: không tìm thấy {preview.term_missed.join(', ')} trong file.</p>
              )}
            </>
          )}
        </>
      )}

      {step === 4 && (
        <div className="summary">
          <strong>Tóm tắt các bước bảo vệ:</strong>
          <ul>
            {pwEnabled && <li>Đặt mật khẩu mở file (AES-256)</li>}
            {permEnabled && <li>Chặn in / sao chép / chỉnh sửa / chú thích</li>}
            {wmEnabled && <li>Thêm watermark{wmSuffix.trim() ? ` (kèm ${wmSuffix.trim()})` : ''}</li>}
            {sanitize && <li>Làm sạch metadata</li>}
            {redactEnabled && <li>Xoá {checked.size} vùng nhạy cảm đã chọn</li>}
            {!pwEnabled && !permEnabled && !wmEnabled && !sanitize && !redactEnabled && (
              <li>Không có tuỳ chọn nào — file sẽ được giữ nguyên.</li>
            )}
          </ul>
          {err && <p className="error">{err}</p>}
        </div>
      )}

      <div className="actions">
        {step > 1 && (
          <button className="ghost" onClick={back} disabled={busy || previewing}>
            Quay lại
          </button>
        )}
        <button className="cta" onClick={next} disabled={busy || previewing || (step === 1 && !file)}>
          {previewing ? 'Đang xem…' : busy ? 'Đang xử lý…' : ctaLabel}
        </button>
      </div>

      <p className="disclaimer">
        Redact xoá vĩnh viễn văn bản khỏi nội dung file (không chỉ bôi đen). File tạm tự xóa sau 24
        giờ.
      </p>
    </>
  )
}

interface LibraryItem {
  id: number
  path: string
  ten: string
  mon: string
  lop: string
  nam: string
  loai: string
  pages: number
  size: number
  created_at: number
  indexed_at: number
  snippet: string
  root?: string
  cloud_file_id?: string
  cloud_name?: string
}

interface CloudItem {
  name: string
  mon: string
  file_id: string
  size_hint?: number | null
}

interface LibraryStats {
  total: number
  by_mon: Record<string, number>
  by_lop: Record<string, number>
  by_nam: Record<string, number>
  by_loai: Record<string, number>
  by_root?: Record<string, number>
}

const ROOT_OPTIONS: SelectOption[] = [
  { value: '', label: 'Nguồn (tất cả)' },
  { value: 'local,convert', label: 'Máy' },
  { value: 'drive', label: 'Drive' },
]

function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fileNameFromPath(p: string): string {
  const i = p.lastIndexOf('/')
  const j = p.lastIndexOf('\\')
  const k = Math.max(i, j)
  return k >= 0 ? p.slice(k + 1) : p
}

function countOptions(rec: Record<string, number> | undefined, allLabel: string): SelectOption[] {
  return [{ value: '', label: allLabel }].concat(
    Object.keys(rec ?? {})
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b, 'vi'))
      .map((k) => ({ value: k, label: `${k} (${rec![k]})` })),
  )
}

function LibraryScreen() {
  const [q, setQ] = useState('')
  const [qDeb, setQDeb] = useState('')
  const [mon, setMon] = useState('')
  const [lop, setLop] = useState('')
  const [nam, setNam] = useState('')
  const [loai, setLoai] = useState('')
  const [root, setRoot] = useState('')
  const [items, setItems] = useState<LibraryItem[]>([])
  const [stats, setStats] = useState<LibraryStats | null>(null)
  const [driveAvailable, setDriveAvailable] = useState(false)
  const [googleLinked, setGoogleLinked] = useState(false)
  const [googleEmail, setGoogleEmail] = useState<string | null>(null)
  const [driveBusyId, setDriveBusyId] = useState<number | null>(null)
  const [driveMsg, setDriveMsg] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [rescanning, setRescanning] = useState(false)
  const [rescanMsg, setRescanMsg] = useState<string | null>(null)
  const [editId, setEditId] = useState<number | null>(null)
  const [edit, setEdit] = useState({ ten: '', mon: '', lop: '', nam: '', loai: '' })
  const [cloud, setCloud] = useState<CloudItem[]>([])
  const [cloudBusyId, setCloudBusyId] = useState<string | null>(null)
  const [cloudErr, setCloudErr] = useState<string | null>(null)

  useEffect(() => {
    const t = window.setTimeout(() => setQDeb(q), 400)
    return () => window.clearTimeout(t)
  }, [q])

  const fetchCloud = useCallback(async () => {
    setCloudErr(null)
    try {
      const res = await api('/library/cloud')
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setCloud(data.items ?? [])
    } catch (e) {
      setCloudErr(e instanceof Error ? e.message : 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    }
  }, [])

  useEffect(() => {
    if (googleLinked) fetchCloud()
  }, [googleLinked, fetchCloud])

  const fetchItems = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const params = new URLSearchParams()
      if (qDeb) params.set('q', qDeb)
      if (mon) params.set('mon', mon)
      if (lop) params.set('lop', lop)
      if (nam) params.set('nam', nam)
      if (loai) params.set('loai', loai)
      if (root) params.set('root', root)
      const res = await api(`/library?${params.toString()}`)
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setItems(data.items ?? [])
      setStats(data.stats ?? null)
      setDriveAvailable(!!data.drive_available)
      setGoogleLinked(!!data.google_linked)
      setGoogleEmail(data.google_email ?? null)
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)',
      )
    } finally {
      setLoading(false)
    }
  }, [qDeb, mon, lop, nam, loai, root])

  useEffect(() => {
    fetchItems()
  }, [fetchItems])

  const rescan = async () => {
    setRescanning(true)
    setErr(null)
    setRescanMsg(null)
    try {
      const res = await api('/library/rescan', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setRescanMsg(
        `Đã thêm ${data.indexed ?? 0} đề mới, cập nhật ${data.updated ?? 0}, bỏ qua ${data.skipped ?? 0}.`,
      )
      await fetchItems()
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)',
      )
    } finally {
      setRescanning(false)
    }
  }

  const startEdit = (it: LibraryItem) => {
    setEditId(it.id)
    setEdit({ ten: it.ten, mon: it.mon, lop: it.lop, nam: it.nam, loai: it.loai })
  }

  const saveEdit = async (id: number) => {
    setErr(null)
    try {
      const fd = new FormData()
      fd.append('ten', edit.ten)
      fd.append('mon', edit.mon)
      fd.append('lop', edit.lop)
      fd.append('nam', edit.nam)
      fd.append('loai', edit.loai)
      const res = await api(`/library/${id}`, { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setEditId(null)
      await fetchItems()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    }
  }

  const removeItem = async (it: LibraryItem) => {
    const label = it.ten || fileNameFromPath(it.path)
    if (!window.confirm(`Xoá "${label}" khỏi kho đề? (File trên đĩa vẫn giữ nguyên)`)) return
    setErr(null)
    try {
      const res = await api(`/library/${it.id}/delete`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      await fetchItems()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    }
  }

  const toDrive = async (it: LibraryItem) => {
    if (driveBusyId !== null) return
    setDriveBusyId(it.id)
    setDriveMsg(null)
    setErr(null)
    try {
      const res = await api(`/library/${it.id}/to-drive`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) {
        setDriveMsg(data.error ?? 'Lỗi máy chủ')
      } else if (data.method === 'google') {
        setDriveMsg(`Đã upload lên Drive của ${googleEmail ?? 'Google'}.`)
        await fetchItems()
      } else if (data.method === 'mount') {
        setDriveMsg(`Đã đưa "${it.ten || fileNameFromPath(it.path)}" lên Drive.`)
        await fetchItems()
      } else {
        setDriveMsg(`Đã đưa "${it.ten || fileNameFromPath(it.path)}" lên Drive.`)
        await fetchItems()
      }
    } catch (e) {
      setErr(
        e instanceof Error ? e.message : 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)',
      )
    } finally {
      setDriveBusyId(null)
      window.setTimeout(() => setDriveMsg(null), 6000)
    }
  }

  const downloadCloud = async (item: CloudItem) => {
    if (cloudBusyId !== null) return
    setCloudBusyId(item.file_id)
    setCloudErr(null)
    setErr(null)
    try {
      const params = new URLSearchParams()
      if (item.mon) params.set('mon', item.mon)
      if (item.name) params.set('name', item.name)
      const res = await api(
        `/library/cloud/${encodeURIComponent(item.file_id)}/download?${params.toString()}`,
        { method: 'POST' },
      )
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      await fetchItems()
      await fetchCloud()
      setDriveMsg(`Đã tải "${item.name}" về máy.`)
      window.setTimeout(() => setDriveMsg(null), 6000)
    } catch (e) {
      setCloudErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    } finally {
      setCloudBusyId(null)
    }
  }

  const byLoai = stats?.by_loai
  const loaiDropdown = !!byLoai && Object.keys(byLoai).length > 0

  return (
    <>
      <p className="eyebrow">Kho đề thi · tìm kiếm toàn văn</p>
      <h1>Kho đề thi của bạn.</h1>
      <p className="sub">
        Tìm nhanh trong nội dung các đề PDF — theo từ khoá, môn, lớp hay năm. Không cần nhớ tên file.
      </p>

      {!driveAvailable && !googleLinked && (
        <p className="warn lib-note">
          Chưa liên kết Google và chưa gắn Drive — chỉ xem được đề trong máy. Vào Cài đặt để liên kết
          Google hoặc mở Google Drive for Desktop.
        </p>
      )}

      {googleLinked && (cloud.length > 0 || cloudErr) && (
        <div className="cloud-box">
          <div className="cloud-head">
            <strong>Đồng bộ từ Drive</strong>
            <span className="lib-count">
              {cloud.length > 0 ? `${cloud.length} file chỉ có trên Drive` : 'Không có file nào'}
            </span>
          </div>
          {cloudErr && <p className="error">{cloudErr}</p>}
          {cloud.length > 0 && (
            <ul className="cloud-list">
              {cloud.map((c) => (
                <li className="cloud-item" key={c.file_id}>
                  <div className="cloud-main">
                    <div className="cloud-name">{c.name || c.file_id}</div>
                    <div className="lib-meta">
                      <span className="badge badge-cloud">Cloud</span>
                      {c.mon && <span className="badge">{c.mon}</span>}
                      {c.size_hint ? <span className="lib-stats">{formatSize(c.size_hint)}</span> : null}
                    </div>
                  </div>
                  <button
                    className="ghost lib-btn"
                    onClick={() => downloadCloud(c)}
                    disabled={cloudBusyId === c.file_id}
                  >
                    {cloudBusyId === c.file_id ? 'Đang tải về…' : 'Tải về máy'}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="lib-filters">
        <input
          className="field"
          placeholder="Tìm trong nội dung đề... (vd: hàm số, phương trình)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="lib-filter-row">
          <FieldSelect
            options={countOptions(stats?.by_mon, 'Môn (tất cả)')}
            value={mon}
            onChange={setMon}
            ariaLabel="Môn"
            wrapClass="ky-inline"
          />
          <FieldSelect
            options={countOptions(stats?.by_lop, 'Lớp (tất cả)')}
            value={lop}
            onChange={setLop}
            ariaLabel="Lớp"
            wrapClass="ky-inline"
          />
          <FieldSelect
            options={countOptions(stats?.by_nam, 'Năm (tất cả)')}
            value={nam}
            onChange={setNam}
            ariaLabel="Năm"
            wrapClass="ky-inline"
          />
          {loaiDropdown ? (
            <FieldSelect
              options={countOptions(byLoai, 'Loại (tất cả)')}
              value={loai}
              onChange={setLoai}
              ariaLabel="Loại"
              wrapClass="ky-inline"
            />
          ) : (
            <input
              className="field"
              placeholder="Loại (vd: HK1, HSG)"
              value={loai}
              onChange={(e) => setLoai(e.target.value)}
            />
          )}
          <FieldSelect
            options={ROOT_OPTIONS}
            value={root}
            onChange={setRoot}
            ariaLabel="Nguồn"
            wrapClass="ky-inline"
          />
        </div>
        <div className="lib-head">
          <span className="lib-count">{stats ? `${stats.total} đề trong kho` : '…'}</span>
          <button className="cta lib-btn" onClick={rescan} disabled={rescanning}>
            {rescanning ? 'Đang dò lại…' : 'Dò lại thư mục'}
          </button>
        </div>
      </div>

      {rescanMsg && <p className="warn lib-note">{rescanMsg}</p>}
      {driveMsg && <p className="lib-drive-msg">{driveMsg}</p>}
      {err && <p className="error">{err}</p>}

      {loading ? (
        <p className="sub lib-empty">Đang tìm kiếm…</p>
      ) : items.length === 0 ? (
        <div className="lib-empty">
          <p>Kho đề trống — quét đề, bấm "Dò lại thư mục" hoặc gắn Google Drive để dùng chung kho đề.</p>
          <button className="cta lib-btn" onClick={rescan} disabled={rescanning}>
            {rescanning ? 'Đang dò lại…' : 'Dò lại thư mục'}
          </button>
        </div>
      ) : (
        <ul className="lib-list">
          {items.map((it) => (
            <li className="lib-item" key={it.id}>
              <div className="lib-title">{it.ten || fileNameFromPath(it.path)}</div>
              <div className="lib-meta">
                {it.root === 'drive' ? (
                  <span className="badge badge-drive">Drive</span>
                ) : (
                  <span className="badge">Máy</span>
                )}
                {it.cloud_file_id && <span className="badge badge-cloud">Đã lưu Drive</span>}
                {it.mon && <span className="badge">{it.mon}</span>}
                {it.lop && <span className="badge">{it.lop}</span>}
                {it.nam && <span className="badge">{it.nam}</span>}
                {it.loai && <span className="badge badge-loai">{it.loai}</span>}
                <span className="lib-stats">
                  {it.pages} trang · {formatSize(it.size)}
                </span>
              </div>
              {it.snippet && <div className="lib-snippet">{it.snippet}</div>}
              <div className="lib-item-actions">
                <button
                  className="cta link lib-btn"
                  onClick={() =>
                    downloadFile(`/library/${it.id}/download`, `${(it.ten || fileNameFromPath(it.path)).replace(/\.pdf$/i, '')}.pdf`)
                  }
                >
                  Tải xuống
                </button>
                {it.root !== 'drive' && !it.cloud_file_id && (driveAvailable || googleLinked) && (
                  <button className="ghost lib-btn" onClick={() => toDrive(it)} disabled={driveBusyId === it.id}>
                    {driveBusyId === it.id ? 'Đang đưa lên…' : 'Đưa lên Drive'}
                  </button>
                )}
                <button className="ghost lib-btn" onClick={() => startEdit(it)}>
                  Sửa
                </button>
                <button className="ghost lib-btn danger" onClick={() => removeItem(it)}>
                  Xoá
                </button>
              </div>
              {editId === it.id && (
                <div className="lib-edit">
                  <input
                    className="field"
                    placeholder="Tên đề"
                    value={edit.ten}
                    onChange={(e) => setEdit({ ...edit, ten: e.target.value })}
                  />
                  <div className="row">
                    <input
                      className="field"
                      placeholder="Môn"
                      value={edit.mon}
                      onChange={(e) => setEdit({ ...edit, mon: e.target.value })}
                    />
                    <input
                      className="field"
                      placeholder="Lớp"
                      value={edit.lop}
                      onChange={(e) => setEdit({ ...edit, lop: e.target.value })}
                    />
                  </div>
                  <div className="row">
                    <input
                      className="field"
                      placeholder="Năm"
                      value={edit.nam}
                      onChange={(e) => setEdit({ ...edit, nam: e.target.value })}
                    />
                    <input
                      className="field"
                      placeholder="Loại"
                      value={edit.loai}
                      onChange={(e) => setEdit({ ...edit, loai: e.target.value })}
                    />
                  </div>
                  <div className="actions">
                    <button className="cta lib-btn" onClick={() => saveEdit(it.id)}>
                      Lưu
                    </button>
                    <button className="ghost lib-btn" onClick={() => setEditId(null)}>
                      Hủy
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function AuthScreen({ onAuthed }: { onAuthed: (user: User) => void }) {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [regPass, setRegPass] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const doLogin = async () => {
    setErr(null)
    if (!login.trim() || !password) return setErr('Nhập email/username và mật khẩu')
    setBusy(true)
    try {
      const res = await authApi('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login: login.trim(), password }),
      })
      const data = await res.json()
      if (!res.ok) {
        if (res.status === 429) return setErr('Thử lại sau 60 giây')
        return setErr(data.error ?? 'Đăng nhập thất bại')
      }
      localStorage.setItem('elena_token', data.token)
      localStorage.setItem('elena_user', JSON.stringify(data.user))
      onAuthed(data.user)
    } catch {
      setErr('Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    } finally {
      setBusy(false)
    }
  }

  const doRegister = async () => {
    setErr(null)
    if (!email.trim() || !/@/.test(email.trim())) return setErr('Nhập email hợp lệ')
    if (!username.trim()) return setErr('Nhập username')
    if (!fullName.trim()) return setErr('Nhập họ tên')
    if (regPass.length < 8 || !/[A-Za-z]/.test(regPass) || !/\d/.test(regPass))
      return setErr('Mật khẩu phải tối thiểu 8 ký tự, gồm chữ và số')
    setBusy(true)
    try {
      const res = await authApi('/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          username: username.trim(),
          full_name: fullName.trim(),
          password: regPass,
        }),
      })
      const data = await res.json()
      if (!res.ok) return setErr(data.error ?? 'Đăng ký thất bại')
      setTab('login')
      setEmail('')
      setUsername('')
      setFullName('')
      setRegPass('')
      setErr(null)
      setLogin(data.user?.email ?? '')
      setPassword('')
    } catch {
      setErr('Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="card center auth-card">
      <p className="eyebrow">Bộ công cụ tài liệu</p>
      <h1 className="brand auth-brand">Elena</h1>
      <p className="sub">
        Đăng nhập để dùng scan đề, chuyển đổi file, bảo vệ PDF và kho đề thi. Tài khoản được lưu cục
        bộ trên máy này.
      </p>
      <div className="tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'login'}
          className={`tab ${tab === 'login' ? 'active' : ''}`}
          onClick={() => {
            setTab('login')
            setErr(null)
          }}
        >
          Đăng nhập
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'register'}
          className={`tab ${tab === 'register' ? 'active' : ''}`}
          onClick={() => {
            setTab('register')
            setErr(null)
          }}
        >
          Đăng ký
        </button>
      </div>

      {tab === 'login' ? (
        <>
          <input
            className="field"
            placeholder="Email hoặc username"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doLogin()}
          />
          <input
            className="field"
            type="password"
            placeholder="Mật khẩu"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doLogin()}
          />
          {err && <p className="error">{err}</p>}
          <button className="cta" onClick={doLogin} disabled={busy}>
            {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
        </>
      ) : (
        <>
          <input
            className="field"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className="field"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            className="field"
            placeholder="Họ tên"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
          <input
            className="field"
            type="password"
            placeholder="Mật khẩu (tối thiểu 8 ký tự, gồm chữ và số)"
            value={regPass}
            onChange={(e) => setRegPass(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doRegister()}
          />
          {err && <p className="error">{err}</p>}
          <button className="cta" onClick={doRegister} disabled={busy}>
            {busy ? 'Đang đăng ký…' : 'Tạo tài khoản'}
          </button>
        </>
      )}
      <p className="disclaimer">Chưa có tài khoản? Dùng tab "Đăng ký" để tạo — miễn phí, không cần mạng.</p>
    </main>
  )
}

function UserHeader({
  user,
  onSettings,
  onLogout,
}: {
  user: User
  onSettings: () => void
  onLogout: () => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const name = user.full_name || user.username
  const initial = (name.trim()[0] ?? '?').toUpperCase()

  return (
    <div className="header">
      <span className="header-brand">Elena</span>
      <div className="header-actions">
        <div className="user-menu" ref={rootRef}>
          <button
            type="button"
            className="user-menu-trigger"
            ref={triggerRef}
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={open}
          >
            <span className="user-avatar" aria-hidden="true">{initial}</span>
            <span className="user-name">{name}</span>
            <svg className={`user-chevron${open ? ' is-open' : ''}`} viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M3.5 6 8 10.5 12.5 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {open && (
            <div className="user-menu-pop" role="menu" aria-label="Menu người dùng">
              <button
                type="button"
                role="menuitem"
                className="user-menu-item"
                onClick={() => {
                  setOpen(false)
                  onSettings()
                }}
              >
                <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="8" cy="8" r="2.4" />
                  <path d="M8 1.6v2M8 12.4v2M1.6 8h2M12.4 8h2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4M12.5 3.5l-1.4 1.4M4.9 11.1l-1.4 1.4" />
                </svg>
                Cài đặt
              </button>
              <div className="user-menu-sep" role="separator" />
              <button
                type="button"
                role="menuitem"
                className="user-menu-item danger"
                onClick={() => {
                  setOpen(false)
                  onLogout()
                }}
              >
                <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M9.5 3h-5A1.5 1.5 0 0 0 3 4.5v7A1.5 1.5 0 0 0 4.5 13h5" />
                  <path d="M6.5 8H14M11.5 5.5 14 8l-2.5 2.5" />
                </svg>
                Đăng xuất
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const NAV_ITEMS: { id: Tool; label: string; icon: ReactNode }[] = [
  { id: 'scan', label: 'Scan đề', icon: <ScanIcon /> },
  { id: 'convert', label: 'Chuyển đổi file', icon: <ConvertIcon /> },
  { id: 'protect', label: 'Bảo vệ PDF', icon: <ProtectIcon /> },
  { id: 'library', label: 'Kho đề thi', icon: <LibraryIcon /> },
]

function SideNav({
  open,
  onOpenChange,
  active,
  onSelect,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  active: Tool | null
  onSelect: (t: Tool) => void
}) {
  const drawerRef = useRef<HTMLDivElement>(null)
  const railRef = useRef<HTMLButtonElement>(null)
  const firstItemRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    firstItemRef.current?.focus()
    const onDown = (e: globalThis.MouseEvent) => {
      const t = e.target as Node
      if (
        drawerRef.current &&
        !drawerRef.current.contains(t) &&
        railRef.current &&
        !railRef.current.contains(t)
      ) {
        onOpenChange(false)
      }
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange(false)
        railRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onOpenChange])

  return (
    <>
      <button
        ref={railRef}
        type="button"
        className="nav-rail"
        aria-label="Mở menu công cụ"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <svg
          viewBox="0 0 16 16"
          width="17"
          height="17"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" />
          <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" />
          <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" />
          <rect x="9" y="9" width="4.5" height="4.5" rx="1" />
        </svg>
      </button>
      <div
        ref={drawerRef}
        className={`nav-drawer${open ? ' open' : ''}`}
        role="navigation"
        aria-label="Danh sách công cụ"
        inert={!open}
      >
        <div className="nav-drawer-head">
          <span className="nav-drawer-title">Công cụ</span>
          <button
            type="button"
            className="nav-close"
            aria-label="Đóng menu công cụ"
            onClick={() => onOpenChange(false)}
          >
            <svg
              viewBox="0 0 16 16"
              width="15"
              height="15"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M9.5 3.5 5 8l4.5 4.5" />
            </svg>
          </button>
        </div>
        <ul className="nav-list">
          {NAV_ITEMS.map((item, i) => (
            <li key={item.id}>
              <button
                ref={i === 0 ? firstItemRef : undefined}
                type="button"
                className={`nav-item${active === item.id ? ' active' : ''}`}
                aria-current={active === item.id ? 'page' : undefined}
                onClick={() => onSelect(item.id)}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}

function SettingsScreen({ user, onLoggedOut }: { user: User; onLoggedOut: () => void }) {
  const [google, setGoogle] = useState<{ linked: boolean; email: string | null; configured: boolean } | null>(null)
  const [drive, setDrive] = useState<{ configured: boolean; available: boolean; use_mount: boolean } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [oldPw, setOldPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [newPw2, setNewPw2] = useState('')
  const [pwBusy, setPwBusy] = useState(false)
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkMsg, setLinkMsg] = useState<string | null>(null)
  const linkTimer = useRef<number | null>(null)

  const loadSettings = useCallback(async () => {
    setErr(null)
    try {
      const res = await api('/settings')
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setGoogle(data.google)
      setDrive(data.drive)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    }
  }, [])

  useEffect(() => {
    loadSettings()
    return () => {
      if (linkTimer.current) window.clearInterval(linkTimer.current)
    }
  }, [loadSettings])

  const changePassword = async () => {
    setErr(null)
    setMsg(null)
    if (!oldPw) return setErr('Nhập mật khẩu cũ')
    if (newPw.length < 8 || !/[A-Za-z]/.test(newPw) || !/\d/.test(newPw))
      return setErr('Mật khẩu mới phải tối thiểu 8 ký tự, gồm chữ và số')
    if (newPw !== newPw2) return setErr('Mật khẩu mới không khớp')
    setPwBusy(true)
    try {
      const res = await api('/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old: oldPw, new: newPw }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Đổi mật khẩu thất bại')
      setOldPw('')
      setNewPw('')
      setNewPw2('')
      setMsg('Đã đổi mật khẩu thành công')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    } finally {
      setPwBusy(false)
    }
  }

  const startLink = async () => {
    setErr(null)
    setMsg(null)
    setLinkMsg(null)
    setLinkBusy(true)
    try {
      const res = await api('/auth/google/start', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      window.open(data.url, '_blank')
      setLinkMsg('Đang chờ bạn hoàn tất đăng nhập Google trong tab mới…')
      let waited = 0
      linkTimer.current = window.setInterval(async () => {
        waited += 2000
        try {
          const r = await api('/auth/google/status', { method: 'POST' })
          const d = await r.json()
          if (d.linked) {
            if (linkTimer.current) window.clearInterval(linkTimer.current)
            setLinkBusy(false)
            setLinkMsg('Đã liên kết tài khoản Google thành công')
            await loadSettings()
            return
          }
          if (d.failure) {
            if (linkTimer.current) window.clearInterval(linkTimer.current)
            setLinkBusy(false)
            setLinkMsg(d.failure)
            return
          }
          if (waited >= 180000) {
            if (linkTimer.current) window.clearInterval(linkTimer.current)
            setLinkBusy(false)
            setLinkMsg('Hết thời gian chờ — bạn có thể bấm liên kết lại')
          }
        } catch {
          /* giữ poll */
        }
      }, 2000)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
      setLinkBusy(false)
    }
  }

  const unlinkGoogle = async () => {
    setErr(null)
    setMsg(null)
    try {
      const res = await api('/auth/google/unlink', { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setMsg('Đã ngắt liên kết Google')
      await loadSettings()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    }
  }

  const toggleMount = async (val: boolean) => {
    setErr(null)
    setMsg(null)
    try {
      const res = await api('/settings/mount-toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_mount: val }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Lỗi máy chủ')
      setDrive((d) => (d ? { ...d, use_mount: val } : d))
      setMsg(val ? 'Đã bật lưu vào Drive gắn (mount)' : 'Đã tắt lưu vào Drive gắn (mount)')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Lỗi máy chủ')
    }
  }

  return (
    <>
      <p className="eyebrow">Cài đặt · tài khoản &amp; đồng bộ</p>
      <h1>Cài đặt của bạn.</h1>
      <p className="sub">Quản lý tài khoản cục bộ, liên kết Google Drive và cách lưu file.</p>

      {msg && <p className="lib-drive-msg">{msg}</p>}
      {err && <p className="error">{err}</p>}

      <div className="settings-section">
        <h3>Tài khoản</h3>
        <div className="settings-box">
          <div className="settings-row">
            <span className="setting-label">Email</span>
            <span className="settings-info">{user.email}</span>
          </div>
          <div className="settings-row">
            <span className="setting-label">Username</span>
            <span className="settings-info">{user.username}</span>
          </div>
          <div className="settings-row">
            <span className="setting-label">Họ tên</span>
            <span className="settings-info">{user.full_name}</span>
          </div>
        </div>
        <div className="settings-box">
          <strong className="setting-sub">Đổi mật khẩu</strong>
          <input
            className="field"
            type="password"
            placeholder="Mật khẩu cũ"
            value={oldPw}
            onChange={(e) => setOldPw(e.target.value)}
          />
          <input
            className="field"
            type="password"
            placeholder="Mật khẩu mới (tối thiểu 8 ký tự, gồm chữ và số)"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
          />
          <input
            className="field"
            type="password"
            placeholder="Nhập lại mật khẩu mới"
            value={newPw2}
            onChange={(e) => setNewPw2(e.target.value)}
          />
          <button className="cta lib-btn" onClick={changePassword} disabled={pwBusy}>
            {pwBusy ? 'Đang đổi…' : 'Đổi mật khẩu'}
          </button>
        </div>
        <div className="settings-box">
          <button className="ghost lib-btn" onClick={onLoggedOut}>
            Đăng xuất
          </button>
        </div>
      </div>

      <div className="settings-section">
        <h3>Google Drive</h3>
        <div className="settings-box">
          {google == null ? (
            <span className="settings-info">Đang tải…</span>
          ) : google.linked ? (
            <div className="settings-row">
              <div>
                <div className="setting-label">Đã liên kết</div>
                <div className="settings-info">{google.email}</div>
              </div>
              <button className="ghost lib-btn" onClick={unlinkGoogle}>
                Ngắt liên kết
              </button>
            </div>
          ) : google.configured ? (
            <div className="settings-row">
              <div className="settings-info">
                Liên kết tài khoản Google để "Kho đề thi" upload trực tiếp vào Drive của bạn (không cần
                Drive for Desktop).
              </div>
              <button className="cta lib-btn" onClick={startLink} disabled={linkBusy}>
                {linkBusy ? 'Đang liên kết…' : 'Liên kết tài khoản Google'}
              </button>
            </div>
          ) : (
            <p className="warn settings-note">Chưa cấu hình Google trên máy</p>
          )}
          {linkMsg && <p className="lib-drive-msg">{linkMsg}</p>}
        </div>
      </div>

      <div className="settings-section">
        <h3>Thư mục Drive gắn (mount)</h3>
        <div className="settings-box">
          <div className="settings-row">
            <div className="settings-info">
              <div className="setting-label">Dùng thư mục Drive gắn</div>
              <span>
                {drive?.configured ? 'SCANDE_DRIVE_ROOT đã cấu hình' : 'Chưa cấu hình SCANDE_DRIVE_ROOT'}
                {drive?.available ? ' — Drive đang được gắn' : drive?.configured ? ' — Drive chưa được gắn' : ''}
              </span>
            </div>
            <label className="switch">
              <input
                type="checkbox"
                checked={drive?.use_mount ?? true}
                onChange={(e) => toggleMount(e.target.checked)}
              />
              <span className="slider" aria-hidden="true" />
            </label>
          </div>
        </div>
      </div>
    </>
  )
}

function App() {
  const [tool, setTool] = useState<Tool>('scan')
  const [navOpen, setNavOpen] = useState(false)
  const [view, setView] = useState<View>('launcher')
  const [job, setJob] = useState<JobStatus | null>(null)
  const [user, setUser] = useState<User | null>(getStoredUser())

  useEffect(() => {
    const onLogout = () => {
      setUser(null)
      setView('launcher')
      setJob(null)
    }
    window.addEventListener(LOGOUT_EVENT, onLogout)
    return () => window.removeEventListener(LOGOUT_EVENT, onLogout)
  }, [])

  const [link, setLink] = useState('')
  const [mon, setMon] = useState('')
  const [tenDe, setTenDe] = useState('')
  const [ky, setKy] = useState(deriveKy())
  const [err, setErr] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [cvFile, setCvFile] = useState<File | null>(null)
  const [cvMon, setCvMon] = useState('')
  const [cvTarget, setCvTarget] = useState('pdf')
  const [cvErr, setCvErr] = useState<string | null>(null)
  const [cvSubmitting, setCvSubmitting] = useState(false)

  const fileRef = useRef<HTMLInputElement>(null)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [])

  const switchTool = (t: Tool) => {
    setTool(t)
    setView('form')
    setJob(null)
    setErr(null)
    setCvErr(null)
  }

  const openSettings = () => {
    setView('settings')
    setJob(null)
    setErr(null)
    setCvErr(null)
  }

  const goLauncher = () => {
    setView('launcher')
    setJob(null)
    setErr(null)
    setCvErr(null)
  }

  const logout = () => {
    api('/auth/logout', { method: 'POST' })
      .catch(() => {
        /* máy chủ không quan trọng khi đăng xuất */
      })
      .finally(() => {
        clearSession()
        window.dispatchEvent(new Event(LOGOUT_EVENT))
      })
  }

  const submitScan = async () => {
    setErr(null)
    const linkErr = checkLink(link)
    if (linkErr) return setErr(linkErr)
    if (!mon.trim()) return setErr('Nhập tên môn học')
    if (!tenDe.trim()) return setErr('Nhập tên đề')
    setSubmitting(true)
    try {
      const res = await api('/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link: link.trim(), mon: mon.trim(), ten_de: tenDe.trim(), ky }),
      })
      const data = await res.json()
      if (!res.ok) return setErr(data.error ?? 'Lỗi máy chủ')
      setJob({ job_id: data.job_id, status: 'queued', ok: null, brief: [], error: null, kind: 'scan' })
      setView('processing')
    } catch {
      setErr('Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    } finally {
      setSubmitting(false)
    }
  }

  const submitConvert = async () => {
    setCvErr(null)
    if (!cvFile) return setCvErr('Chọn file cần chuyển đổi')
    if (!cvMon.trim()) return setCvErr('Nhập tên môn học')
    const ext = (cvFile.name.split('.').pop() || '').toLowerCase()
    if (!SOURCE_EXTS.split(', ').includes(ext))
      return setCvErr(`Định dạng chưa hỗ trợ: .${ext} (hỗ trợ: ${SOURCE_EXTS})`)
    setCvSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('file', cvFile)
      fd.append('mon', cvMon.trim())
      fd.append('target', cvTarget)
      const res = await api('/convert', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) return setCvErr(data.error ?? 'Lỗi máy chủ')
      setJob({ job_id: data.job_id, status: 'queued', ok: null, brief: [], error: null, kind: 'convert' })
      setView('processing')
    } catch {
      setCvErr('Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)')
    } finally {
      setCvSubmitting(false)
    }
  }

  const submitProtect = async (file: File, config: unknown): Promise<string | null> => {
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('config', JSON.stringify(config))
      const res = await api('/protect', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) return data.error ?? 'Lỗi máy chủ'
      setJob({ job_id: data.job_id, status: 'queued', ok: null, brief: [], error: null, kind: 'protect' })
      setView('processing')
      return null
    } catch {
      return 'Không kết nối được máy chủ (đã chạy API trên cổng 8000 chưa?)'
    }
  }

  useEffect(() => {
    const jobId = job?.job_id
    const kind = job?.kind
    if (view !== 'processing' || !jobId) return
    timer.current = window.setInterval(async () => {
      try {
        const res = await api(`/jobs/${jobId}`)
        const data: JobStatus = await res.json()
        setJob(data)
        if (data.status === 'done' || data.status === 'failed') {
          if (timer.current) window.clearInterval(timer.current)
          setView('result')
        }
      } catch {
        /* giữ poll */
      }
    }, kind === 'protect' ? 2000 : 3000)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [view, job?.job_id, job?.kind])

  const isConvert = job?.kind === 'convert'
  const isProtect = job?.kind === 'protect'

  if (!user) {
    return (
      <div className="app">
        <AuthScreen onAuthed={setUser} />
      </div>
    )
  }

  return (
    <div className="app">
      <div className="leaf" aria-hidden="true">
        <svg viewBox="0 0 60 90">
          <path d="M30 88 C 8 62, 6 28, 30 4 C 54 28, 52 62, 30 88 Z" />
        </svg>
      </div>

      {user && <UserHeader user={user} onSettings={openSettings} onLogout={logout} />}
      {user && (
        <SideNav
          open={navOpen}
          onOpenChange={setNavOpen}
          active={view === 'form' ? tool : null}
          onSelect={(t) => {
            switchTool(t)
            setNavOpen(false)
          }}
        />
      )}

      {view === 'launcher' && (
        <main className="card center launcher">
          <p className="eyebrow">Bộ công cụ tài liệu</p>
          <h1 className="brand">Elena</h1>
          <p className="sub">Quét đề thi, chuyển đổi định dạng, bảo vệ PDF và tra cứu kho đề — chọn một công cụ để bắt đầu.</p>
          <div className="tools">
            <ToolCard
              title="Scan đề"
              desc="Dán link Scribd/Drive, nhận PDF sạch với lớp chữ nhận diện (OCR), giữ nguyên ảnh và công thức."
              icon={<ScanIcon />}
              onClick={() => switchTool('scan')}
            />
            <ToolCard
              title="Chuyển đổi file"
              desc="Đổi định dạng DOCX, XLSX, PDF, TXT, HTML… giữ nguyên hình ảnh, không bao giờ mất nội dung."
              icon={<ConvertIcon />}
              onClick={() => switchTool('convert')}
            />
            <ToolCard
              title="Bảo vệ PDF"
              desc="Đặt mật khẩu, chặn in/sao chép, thêm watermark, làm sạch metadata và xoá thông tin nhạy cảm."
              icon={<ProtectIcon />}
              onClick={() => switchTool('protect')}
            />
            <ToolCard
              title="Kho đề thi"
              desc="Tìm kiếm toàn văn trong kho đề PDF — nhanh chóng theo từ khoá, môn, lớp, năm."
              icon={<LibraryIcon />}
              onClick={() => switchTool('library')}
            />
            <ToolCard
              title="Cài đặt"
              desc="Tài khoản, đổi mật khẩu, liên kết Google Drive và cách lưu file."
              icon={<SettingsIcon />}
              onClick={openSettings}
            />
          </div>
        </main>
      )}

      {view === 'form' && (
        <main className={`card center ${tool === 'library' ? 'wide' : ''}`}>
          {tool === 'scan' ? (
            <>
              <p className="eyebrow">Scan đề · Scribd → PDF</p>
              <h1>Đưa link đề thi vào, nhận file PDF sạch.</h1>
              <p className="sub">
                Dán link embed (fullscreen), chọn môn và tên đề. Phần mềm tự quét từng trang, giữ
                nguyên ảnh và công thức, thêm lớp chữ có thể chọn.
              </p>
              <input
                className="field"
                placeholder="https://www.scribd.com/document/…  (#fullscreen=1)"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submitScan()}
              />
              <div className="row">
                <input
                  className="field"
                  placeholder="Môn học (vd: Giải tích 1)"
                  value={mon}
                  onChange={(e) => setMon(e.target.value)}
                />
                <input
                  className="field"
                  placeholder="Tên đề (vd: Đề giữa kỳ 2024)"
                  value={tenDe}
                  onChange={(e) => setTenDe(e.target.value)}
                />
                <FieldSelect
                  options={KYS.map((k) => ({ value: k, label: k }))}
                  value={ky}
                  onChange={setKy}
                  ariaLabel="Học kỳ"
                  wrapClass="ky-inline"
                />
              </div>
              {err && <p className="error">{err}</p>}
              <button className="cta" onClick={submitScan} disabled={submitting}>
                {submitting ? 'Đang gửi…' : 'Scan đề'}
              </button>
              <p className="disclaimer">
                Chỉ dùng cho tài liệu cá nhân/giáo dục. File tạm tự xóa sau 24 giờ.
              </p>
            </>
          ) : tool === 'convert' ? (
            <>
              <p className="eyebrow">Chuyển đổi file · giữ nguyên ảnh</p>
              <h1>Đưa file vào, nhận đúng định dạng bạn cần.</h1>
              <p className="sub">
                Chữ chuyển đổi bình thường (vẫn edit được). Ảnh trong file — hình câu hỏi, hình vẽ —
                được giữ nguyên vẹn và thêm lớp chữ nhận diện (OCR), không bao giờ hỏng hay mất.
              </p>
              <input
                ref={fileRef}
                type="file"
                className="hidden-file"
                accept=".docx,.doc,.xlsx,.xls,.pptx,.ppt,.odt,.ods,.odp,.rtf,.txt,.csv,.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.html"
                onChange={(e) => setCvFile(e.target.files?.[0] ?? null)}
              />
              <div
                className="dropzone"
                role="button"
                tabIndex={0}
                onClick={() => fileRef.current?.click()}
                onKeyDown={(e) => e.key === 'Enter' && fileRef.current?.click()}
              >
                {cvFile ? (
                  <span className="fname">{cvFile.name}</span>
                ) : (
                  <span>
                    Kéo thả file vào đây hoặc bấm chọn
                    <br />
                    <small>{SOURCE_EXTS}</small>
                  </span>
                )}
              </div>
              <input
                className="field"
                placeholder="Môn học (vd: Giải tích 1) — file sẽ lưu vào D:\Chuyen doi\{Môn}"
                value={cvMon}
                onChange={(e) => setCvMon(e.target.value)}
              />
              <FieldSelect
                options={TARGET_OPTIONS}
                value={cvTarget}
                onChange={setCvTarget}
                ariaLabel="Định dạng đích"
                wrapClass="ky-block"
              />
              {cvErr && <p className="error">{cvErr}</p>}
              <button className="cta" onClick={submitConvert} disabled={cvSubmitting}>
                {cvSubmitting ? 'Đang gửi…' : 'Chuyển đổi file'}
              </button>
              <p className="disclaimer">
                Ảnh trong file đi qua nguyên lý scan-de: giữ nguyên vẹn + lớp text OCR. File tạm tự
                xóa sau 24 giờ.
              </p>
            </>
          ) : tool === 'protect' ? (
            <ProtectWizard submitProtect={submitProtect} />
          ) : (
            <LibraryScreen />
          )}
        </main>
      )}

      {view === 'settings' && (
        <main className="card center wide">
          <div className="settings-top">
            <button type="button" className="ghost" onClick={goLauncher}>
              <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M9.5 3.5 5 8l4.5 4.5" />
              </svg>
              Quay lại
            </button>
          </div>
          <SettingsScreen user={user!} onLoggedOut={logout} />
        </main>
      )}

      {view === 'processing' && (
        <main className="card center">
          <SandDrift />
          <p className="eyebrow">Đang xử lý</p>
          <h1>Gõ cát, gió thổi…</h1>
          <p className="sub">
            {job?.job_id} —{' '}
            {isProtect
              ? 'bảo vệ PDF: đặt mật khẩu, khoá quyền, watermark, làm sạch metadata, xoá thông tin nhạy cảm'
              : isConvert
                ? 'chuyển đổi định dạng, nhận diện chữ trong ảnh'
                : 'quét trang, nhận diện chữ, dựng PDF'}.
            {isProtect ? ' Chỉ mất vài giây.' : ' Thường mất 1–2 phút.'}
          </p>
          <WaterLine done={false} />
        </main>
      )}

      {view === 'result' && (
        <main className="card center">
          <p className="eyebrow">
            {job?.ok
              ? isConvert
                ? 'Xong — file đã lưu'
                : isProtect
                  ? 'Xong — PDF đã bảo vệ'
                  : 'Xong — PDF đã lưu'
              : 'Không tạo được file'}
          </p>
          <h1>{job?.ok ? 'File đã sẵn sàng.' : 'Đã dừng với lỗi.'}</h1>
          <pre className="brief">{job?.brief?.join('\n')}</pre>
          <div className="actions">
            {job?.ok && (
              <button className="cta link" onClick={() => downloadFile(`/jobs/${job.job_id}/download`, `ket_qua_${job.job_id}.${job.kind === 'convert' ? cvTarget : 'pdf'}`)}>
                {isProtect ? 'Tải PDF đã bảo vệ' : isConvert ? 'Tải file về' : 'Tải PDF về'}
              </button>
            )}
            <button className="ghost" onClick={() => switchTool(isProtect ? 'protect' : isConvert ? 'convert' : 'scan')}>
              {isProtect ? 'Bảo vệ file khác' : isConvert ? 'Chuyển đổi khác' : 'Scan đề khác'}
            </button>
          </div>
        </main>
      )}
    </div>
  )
}

export default App
