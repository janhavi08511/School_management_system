import { useEffect, useMemo, useState } from 'react'
import { apiRequest, downloadFile } from './api'
import './Student.css'

const STUDENT_TABS = [
  ['overview', 'Overview'],
  ['notes', 'Course notes'],
  ['fees', 'My fees'],
  ['performance', 'Performance'],
  ['profile', 'My profile'],
]

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString()
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function StudentDashboard({ token, onLogout }) {
  const [activeTab, setActiveTab] = useState('overview')
  const [profile, setProfile] = useState(null)
  const [notes, setNotes] = useState([])
  const [fees, setFees] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [notesSearch, setNotesSearch] = useState('')
  const [notesCourseFilter, setNotesCourseFilter] = useState('all')
  const [selectedReceipt, setSelectedReceipt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [downloadingNoteId, setDownloadingNoteId] = useState(null)
  const [feedback, setFeedback] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      apiRequest('/student/profile', token),
      apiRequest('/student/notes', token),
      apiRequest('/student/fees', token),
      apiRequest('/student/performance', token),
    ])
      .then(([profileData, noteData, feeData, performanceData]) => {
        if (!active) return
        setProfile(profileData)
        setNotes(noteData)
        setFees(feeData)
        setPerformance(performanceData)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [token])

  const visibleNotes = useMemo(() => {
    const search = notesSearch.trim().toLowerCase()
    return notes.filter((note) => {
      const matchesCourse =
        notesCourseFilter === 'all' || String(note.course_id) === notesCourseFilter
      const matchesSearch =
        !search ||
        [
          note.title,
          note.description,
          note.course_name,
          note.course_code,
          note.teacher_name,
          note.original_filename,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(search)
      return matchesCourse && matchesSearch
    })
  }, [notes, notesCourseFilter, notesSearch])

  const latestDueDate = fees?.items
    ?.filter((item) => Number(item.pending_amount) > 0 && item.due_date)
    .map((item) => item.due_date)
    .sort()[0]

  async function handleDownloadNote(note) {
    setDownloadingNoteId(note.id)
    setFeedback(null)
    try {
      await downloadFile(
        `/student/notes/${note.id}/download`,
        token,
        note.original_filename,
      )
      setFeedback({ type: 'success', text: `${note.title} downloaded.` })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setDownloadingNoteId(null)
    }
  }

  async function handleViewReceipt(payment) {
    try {
      const receipt = await apiRequest(
        `/student/fees/payments/${payment.id}/receipt?source=${payment.source}`,
        token,
      )
      setSelectedReceipt(receipt)
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  if (loading) {
    return (
      <main className="student-loading">
        <div className="student-loader" />
        <p>Loading your student dashboard...</p>
      </main>
    )
  }

  const student = profile?.student
  const courses = profile?.courses || []
  const latestNotes = [...notes].slice(0, 4)
  const topCourseAverage = (performance?.courses || []).length
    ? Math.max(...performance.courses.map((course) => Number(course.average_percentage)))
    : 0
  const maximumTrend = Math.max(
    1,
    ...(performance?.trends || []).map((trend) => Number(trend.average_percentage)),
  )

  return (
    <div className="student-app">
      <header className="student-topbar">
        <a className="student-brand" href="#student-home">
          <span className="student-brand-mark">S</span>
          <span>
            <strong>Campus Portal</strong>
            <small>Student dashboard</small>
          </span>
        </a>
        <div className="student-topbar-actions">
          <span className="student-user-chip">{student?.name || 'Student'}</span>
          <button className="student-logout" onClick={onLogout}>Sign out</button>
        </div>
      </header>

      <main className="student-main" id="student-home">
        <section className="student-welcome">
          <div className="student-welcome-copy">
            <p className="student-eyebrow">Your learning space</p>
            <h1>Welcome back, {student?.first_name || student?.name || 'Student'}</h1>
            <p>
              Keep up with your course materials, fee status, and academic progress.
            </p>
          </div>
          <div className="student-welcome-meta">
            <span>Student ID</span>
            <strong>{student?.admission_number || '—'}</strong>
            <small>{student?.class_name || 'Class not assigned'}</small>
          </div>
        </section>

        <nav className="student-tabs" aria-label="Student sections">
          {STUDENT_TABS.map(([tab, label]) => (
            <button
              className={activeTab === tab ? 'student-tab active' : 'student-tab'}
              key={tab}
              onClick={() => setActiveTab(tab)}
              aria-current={activeTab === tab ? 'page' : undefined}
            >
              {label}
            </button>
          ))}
        </nav>

        {feedback && (
          <div className={`student-feedback ${feedback.type}`} role="status">
            <span>{feedback.text}</span>
            <button onClick={() => setFeedback(null)} aria-label="Dismiss message">×</button>
          </div>
        )}

        {activeTab === 'overview' && (
          <section className="student-content">
            <div className="student-stat-grid">
              <article className="student-stat-card">
                <span>Enrolled courses</span>
                <strong>{courses.filter((course) => course.enrollment_status === 'enrolled').length}</strong>
                <small>Current learning</small>
              </article>
              <article className="student-stat-card">
                <span>Available notes</span>
                <strong>{notes.length}</strong>
                <small>From your courses</small>
              </article>
              <article className="student-stat-card">
                <span>Pending fees</span>
                <strong>{formatCurrency(fees?.pending_fees)}</strong>
                <small>Outstanding balance</small>
              </article>
              <article className="student-stat-card">
                <span>Overall average</span>
                <strong>{performance?.assessment_count ? `${performance.overall_average}%` : '—'}</strong>
                <small>{performance?.assessment_count ? `${performance.overall_grade} grade` : 'No results yet'}</small>
              </article>
            </div>

            <div className="student-overview-grid">
              <section className="student-panel">
                <div className="student-panel-heading">
                  <div><p className="student-eyebrow">Course library</p><h2>Recent notes</h2></div>
                  <button className="student-link-button" onClick={() => setActiveTab('notes')}>Browse all</button>
                </div>
                {latestNotes.length === 0 ? (
                  <p className="student-empty">No notes have been uploaded to your courses yet.</p>
                ) : (
                  <div className="student-note-list">
                    {latestNotes.map((note) => (
                      <article className="student-note-row" key={note.id}>
                        <span className="student-file-icon">{note.file_type || 'FILE'}</span>
                        <div className="student-note-row-copy">
                          <strong>{note.title}</strong>
                          <span>{note.course_name} · {formatDate(note.uploaded_at)}</span>
                        </div>
                        <button className="student-link-button" onClick={() => handleDownloadNote(note)}>Download</button>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="student-panel student-due-panel">
                <p className="student-eyebrow">Fee reminder</p>
                <h2>{formatCurrency(fees?.pending_fees)} pending</h2>
                <p>
                  {latestDueDate
                    ? `Next due date: ${formatDate(latestDueDate)}`
                    : 'You have no upcoming fee due dates.'}
                </p>
                <button className="student-primary-button" onClick={() => setActiveTab('fees')}>View fee details</button>
              </section>

              <section className="student-panel">
                <div className="student-panel-heading">
                  <div><p className="student-eyebrow">Your learning</p><h2>Enrolled courses</h2></div>
                  <span className="student-count">{courses.length}</span>
                </div>
                {courses.length === 0 ? (
                  <p className="student-empty">No courses are linked to your profile.</p>
                ) : (
                  <div className="student-course-list">
                    {courses.slice(0, 5).map((course) => (
                      <div className="student-course-row" key={`${course.course_id}-${course.academic_year_id}`}>
                        <span className="student-course-code">{course.course_code}</span>
                        <div><strong>{course.course_name}</strong><small>{course.academic_year} · {course.enrollment_status}</small></div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="student-panel">
                <div className="student-panel-heading">
                  <div><p className="student-eyebrow">Academic snapshot</p><h2>Course averages</h2></div>
                  <button className="student-link-button" onClick={() => setActiveTab('performance')}>View results</button>
                </div>
                {(performance?.courses || []).length === 0 ? (
                  <p className="student-empty">Your course results will appear here.</p>
                ) : (
                  <div className="student-bars">
                    {performance.courses.slice(0, 4).map((course) => (
                      <div className="student-bar-row" key={course.course_id}>
                        <div><span>{course.course_code}</span><strong>{course.average_percentage}%</strong></div>
                        <div className="student-bar"><span style={{ width: `${course.average_percentage}%` }} /></div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </section>
        )}

        {activeTab === 'notes' && (
          <section className="student-panel">
            <div className="student-panel-heading">
              <div><p className="student-eyebrow">Learning resources</p><h2>Course document library</h2><p className="student-muted">Notes shared by teachers for your enrolled courses.</p></div>
              <span className="student-count">{visibleNotes.length} files</span>
            </div>
            <div className="student-library-filters">
              <label>
                Search notes
                <input value={notesSearch} onChange={(event) => setNotesSearch(event.target.value)} placeholder="Title, course, teacher, or filename" />
              </label>
              <label>
                Filter by course
                <select value={notesCourseFilter} onChange={(event) => setNotesCourseFilter(event.target.value)}>
                  <option value="all">All courses</option>
                  {courses.map((course) => (
                    <option key={course.course_id} value={course.course_id}>{course.course_code} · {course.course_name}</option>
                  ))}
                </select>
              </label>
            </div>
            {visibleNotes.length === 0 ? (
              <p className="student-empty">No notes match your search. Try another course or keyword.</p>
            ) : (
              <div className="student-document-grid">
                {visibleNotes.map((note) => (
                  <article className="student-document-card" key={note.id}>
                    <div className="student-document-top">
                      <span className="student-file-icon large">{note.file_type || 'FILE'}</span>
                      <span className="student-file-type">{note.file_type || 'FILE'}</span>
                    </div>
                    <h3>{note.title}</h3>
                    <p className="student-document-description">{note.description || note.original_filename}</p>
                    <dl>
                      <div><dt>Course</dt><dd>{note.course_name} <small>{note.course_code}</small></dd></div>
                      <div><dt>Teacher</dt><dd>{note.teacher_name}</dd></div>
                      <div><dt>Uploaded</dt><dd>{formatDate(note.uploaded_at)}</dd></div>
                    </dl>
                    <button
                      className="student-download-button"
                      onClick={() => handleDownloadNote(note)}
                      disabled={downloadingNoteId === note.id}
                    >
                      {downloadingNoteId === note.id ? 'Preparing download…' : 'Download notes'}
                    </button>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {activeTab === 'fees' && (
          <section className="student-content">
            <div className="student-stat-grid fee-stat-grid">
              <article className="student-stat-card"><span>Total fees</span><strong>{formatCurrency(fees?.total_fees)}</strong><small>All fee records</small></article>
              <article className="student-stat-card"><span>Paid amount</span><strong>{formatCurrency(fees?.paid_fees)}</strong><small>Payments received</small></article>
              <article className="student-stat-card"><span>Pending amount</span><strong>{formatCurrency(fees?.pending_fees)}</strong><small>Amount outstanding</small></article>
              <article className="student-stat-card"><span>Next due date</span><strong className="student-date-value">{latestDueDate ? formatDate(latestDueDate) : '—'}</strong><small>{latestDueDate ? 'Please pay by this date' : 'No pending dated fees'}</small></article>
            </div>
            <section className="student-panel">
              <div className="student-panel-heading"><div><p className="student-eyebrow">Your account</p><h2>Fee status</h2></div></div>
              <div className="student-table-wrap">
                <table className="student-table">
                  <thead><tr><th>Academic year</th><th>Fee</th><th>Total fees</th><th>Paid</th><th>Pending</th><th>Due date</th><th>Status</th></tr></thead>
                  <tbody>
                    {(fees?.items || []).map((item, index) => (
                      <tr key={item.id ? `invoice-${item.id}` : `legacy-${index}`}>
                        <td>{item.academic_year || 'Student balance'}</td>
                        <td>{item.fee_name}</td>
                        <td>{formatCurrency(item.total_fees)}</td>
                        <td>{formatCurrency(item.paid_amount)}</td>
                        <td>{formatCurrency(item.pending_amount)}</td>
                        <td>{formatDate(item.due_date)}</td>
                        <td><span className={`student-status ${item.payment_status}`}>{item.payment_status.replace('_', ' ')}</span></td>
                      </tr>
                    ))}
                    {(fees?.items || []).length === 0 && <tr><td colSpan="7">No fee information is available.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="student-panel">
              <div className="student-panel-heading"><div><p className="student-eyebrow">Transactions</p><h2>Payment history & receipts</h2></div><span className="student-count">{fees?.payment_history?.length || 0} payments</span></div>
              <div className="student-table-wrap">
                <table className="student-table">
                  <thead><tr><th>Date</th><th>Fee</th><th>Academic year</th><th>Amount</th><th>Method</th><th>Reference</th><th>Receipt</th></tr></thead>
                  <tbody>
                    {(fees?.payment_history || []).map((payment) => (
                      <tr key={`${payment.source}-${payment.id}`}>
                        <td>{formatDateTime(payment.paid_at)}</td>
                        <td>{payment.fee_name}</td>
                        <td>{payment.academic_year || '—'}</td>
                        <td>{formatCurrency(payment.amount)}</td>
                        <td>{payment.payment_method.replace('_', ' ')}</td>
                        <td>{payment.transaction_reference || '—'}</td>
                        <td><button className="student-link-button" onClick={() => handleViewReceipt(payment)}>View receipt</button></td>
                      </tr>
                    ))}
                    {(fees?.payment_history || []).length === 0 && <tr><td colSpan="7">No payments have been recorded.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        )}

        {activeTab === 'performance' && (
          <section className="student-content">
            <div className="student-stat-grid">
              <article className="student-stat-card"><span>Overall average</span><strong>{performance?.assessment_count ? `${performance.overall_average}%` : '—'}</strong><small>{performance?.assessment_count ? `${performance.overall_grade} overall grade` : 'No results recorded'}</small></article>
              <article className="student-stat-card"><span>Assessments</span><strong>{performance?.assessment_count || 0}</strong><small>Exams and results</small></article>
              <article className="student-stat-card"><span>Courses assessed</span><strong>{performance?.courses?.length || 0}</strong><small>With recorded marks</small></article>
              <article className="student-stat-card"><span>Highest course average</span><strong>{performance?.courses?.length ? `${topCourseAverage}%` : '—'}</strong><small>Across your courses</small></article>
            </div>
            <div className="student-overview-grid performance-grid">
              <section className="student-panel">
                <div className="student-panel-heading"><div><p className="student-eyebrow">Course-wise summary</p><h2>Academic performance</h2></div></div>
                {(performance?.courses || []).length === 0 ? <p className="student-empty">No assessment results are available yet.</p> : (
                  <div className="student-bars">
                    {performance.courses.map((course) => (
                      <div className="student-bar-row" key={course.course_id}>
                        <div><span>{course.course_code} · {course.course_name}</span><strong>{course.average_percentage}% · {course.grade}</strong></div>
                        <div className="student-bar"><span style={{ width: `${Math.min(course.average_percentage, 100)}%` }} /></div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
              <section className="student-panel">
                <div className="student-panel-heading"><div><p className="student-eyebrow">Progress over time</p><h2>Performance trends</h2></div></div>
                {(performance?.trends || []).length === 0 ? <p className="student-empty">Trends will appear after results are recorded.</p> : (
                  <div className="student-bars">
                    {performance.trends.map((trend) => (
                      <div className="student-bar-row" key={trend.month}>
                        <div><span>{trend.month} · {trend.assessment_count} results</span><strong>{trend.average_percentage}%</strong></div>
                        <div className="student-bar"><span style={{ width: `${Math.min((trend.average_percentage / maximumTrend) * 100, 100)}%` }} /></div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
            <section className="student-panel">
              <div className="student-panel-heading"><div><p className="student-eyebrow">Exam results</p><h2>My results</h2></div><span className="student-count">{performance?.records?.length || 0}</span></div>
              <div className="student-table-wrap">
                <table className="student-table">
                  <thead><tr><th>Exam</th><th>Course</th><th>Academic year</th><th>Marks</th><th>Percentage</th><th>Grade</th><th>Date</th></tr></thead>
                  <tbody>
                    {(performance?.records || []).map((record) => (
                      <tr key={record.id}><td>{record.exam_name}</td><td>{record.course_code} · {record.course_name}</td><td>{record.academic_year}</td><td>{record.marks_obtained} / {record.total_marks}</td><td>{record.percentage}%</td><td><strong>{record.grade}</strong></td><td>{formatDate(record.created_at)}</td></tr>
                    ))}
                    {(performance?.records || []).length === 0 && <tr><td colSpan="7">No exam results are available yet.</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        )}

        {activeTab === 'profile' && student && (
          <section className="student-profile-layout">
            <section className="student-panel student-profile-card">
              <div className="student-avatar">{student.first_name?.charAt(0)}{student.last_name?.charAt(0)}</div>
              <p className="student-eyebrow">Student profile</p>
              <h2>{student.name}</h2>
              <p className="student-muted">{student.admission_number} · {student.class_name || 'Class not assigned'}</p>
              <span className={`student-status ${student.status}`}>{student.status}</span>
            </section>
            <section className="student-panel">
              <div className="student-panel-heading"><div><p className="student-eyebrow">Personal information</p><h2>My details</h2></div></div>
              <dl className="student-profile-details">
                <div><dt>Student ID</dt><dd>{student.admission_number}</dd></div>
                <div><dt>Full name</dt><dd>{student.name}</dd></div>
                <div><dt>Email</dt><dd>{student.email || '—'}</dd></div>
                <div><dt>Phone</dt><dd>{student.phone || '—'}</dd></div>
                <div><dt>Date of birth</dt><dd>{formatDate(student.date_of_birth)}</dd></div>
                <div><dt>Gender</dt><dd>{student.gender || '—'}</dd></div>
                <div><dt>Admission date</dt><dd>{formatDate(student.admission_date)}</dd></div>
                <div><dt>Class / grade</dt><dd>{student.class_name || '—'}</dd></div>
                <div><dt>Address</dt><dd>{student.address || '—'}</dd></div>
                <div><dt>Parent / guardian</dt><dd>{student.parent_guardian_name || '—'}</dd></div>
                <div><dt>Parent contact</dt><dd>{student.parent_contact || '—'}</dd></div>
              </dl>
            </section>
            <section className="student-panel student-full-panel">
              <div className="student-panel-heading"><div><p className="student-eyebrow">Learning plan</p><h2>Enrolled courses</h2></div><span className="student-count">{courses.length}</span></div>
              {courses.length === 0 ? <p className="student-empty">No courses are currently linked to your account.</p> : (
                <div className="student-course-grid">
                  {courses.map((course) => (
                    <article className="student-course-card" key={`${course.course_id}-${course.academic_year_id}`}>
                      <span className="student-course-code">{course.course_code}</span>
                      <strong>{course.course_name}</strong>
                      <small>{course.academic_year}</small>
                      <span className={`student-status ${course.enrollment_status}`}>{course.enrollment_status}</span>
                    </article>
                  ))}
                </div>
              )}
            </section>
          </section>
        )}
      </main>

      {selectedReceipt && (
        <div className="student-modal-backdrop" role="presentation" onClick={() => setSelectedReceipt(null)}>
          <section className="student-receipt" role="dialog" aria-modal="true" aria-labelledby="student-receipt-title" onClick={(event) => event.stopPropagation()}>
            <div className="student-panel-heading">
              <div><p className="student-eyebrow">Payment confirmation</p><h2 id="student-receipt-title">Fee receipt #{selectedReceipt.id}</h2></div>
              <button className="student-link-button" onClick={() => setSelectedReceipt(null)}>Close</button>
            </div>
            <p><strong>{selectedReceipt.student_name}</strong> · {selectedReceipt.admission_number} · {selectedReceipt.class_name}</p>
            <p>{selectedReceipt.fee_name} · {selectedReceipt.academic_year || 'Student fee balance'}</p>
            <p>Paid {formatCurrency(selectedReceipt.amount)} by {selectedReceipt.payment_method.replace('_', ' ')} on {formatDateTime(selectedReceipt.paid_at)}</p>
            <p>Reference: {selectedReceipt.transaction_reference || '—'}</p>
            <button className="student-primary-button" onClick={() => window.print()}>Print receipt</button>
          </section>
        </div>
      )}
    </div>
  )
}

export default StudentDashboard
