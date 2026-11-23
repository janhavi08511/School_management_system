import { useEffect, useState } from 'react'
import { apiRequest, downloadFile } from './api'

const STUDENT_ATTENDANCE_STATUSES = [
  { value: 'present', label: 'Present' },
  { value: 'absent', label: 'Absent' },
  { value: 'late', label: 'Late' },
  { value: 'excused', label: 'Excused' },
]

function getLocalDate() {
  const today = new Date()
  return [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, '0'),
    String(today.getDate()).padStart(2, '0'),
  ].join('-')
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleDateString()
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : '-'
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function TeacherDashboard({ token, onLogout }) {
  const [activeTab, setActiveTab] = useState('overview')
  const [dashboard, setDashboard] = useState(null)
  const [profile, setProfile] = useState(null)
  const [salary, setSalary] = useState({ base_salary: '0.00', payments: [] })
  const [personalAttendance, setPersonalAttendance] = useState([])
  const [attendanceSummary, setAttendanceSummary] = useState({
    percentage: 0,
    present_days: 0,
    absent_days: 0,
    late_days: 0,
    leave_days: 0,
    total_days: 0,
  })
  const [attendanceMonth, setAttendanceMonth] = useState(getLocalDate().slice(0, 7))
  const [attendanceDay, setAttendanceDay] = useState('')
  const [courses, setCourses] = useState([])
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [attendanceDate, setAttendanceDate] = useState(getLocalDate)
  const [academicYear, setAcademicYear] = useState(null)
  const [attendanceRoster, setAttendanceRoster] = useState([])
  const [classFilter, setClassFilter] = useState('all')
  const [attendanceHistory, setAttendanceHistory] = useState([])
  const [attendanceHistoryMonth, setAttendanceHistoryMonth] = useState(
    getLocalDate().slice(0, 7),
  )
  const [showAttendanceHistory, setShowAttendanceHistory] = useState(false)
  const [courseNotes, setCourseNotes] = useState([])
  const [editingNoteId, setEditingNoteId] = useState(null)
  const [editingNoteTitle, setEditingNoteTitle] = useState('')
  const [editingNoteDescription, setEditingNoteDescription] = useState('')
  const [selectedPayslip, setSelectedPayslip] = useState(null)
  const [loading, setLoading] = useState(true)
  const [attendanceLoading, setAttendanceLoading] = useState(true)
  const [personalAttendanceLoading, setPersonalAttendanceLoading] = useState(true)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [notesLoading, setNotesLoading] = useState(true)
  const [attendanceSaving, setAttendanceSaving] = useState(false)
  const [noteUploading, setNoteUploading] = useState(false)
  const [noteSaving, setNoteSaving] = useState(false)
  const [feedback, setFeedback] = useState(null)

  useEffect(() => {
    let active = true
    Promise.all([
      apiRequest('/teacher/dashboard', token),
      apiRequest('/teacher/salary', token),
    ])
      .then(([dashboardData, salaryData]) => {
        if (!active) return
        setDashboard(dashboardData)
        setProfile(dashboardData.profile)
        setCourses(dashboardData.assigned_courses)
        setSalary(salaryData)
        setSelectedCourseId((current) =>
          current ||
          (dashboardData.assigned_courses[0]
            ? String(dashboardData.assigned_courses[0].id)
            : ''),
        )
        if (dashboardData.assigned_courses.length === 0) {
          setAttendanceLoading(false)
          setNotesLoading(false)
        }
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

  useEffect(() => {
    if (!attendanceMonth) return undefined

    let active = true
    apiRequest(`/teacher/attendance?month=${encodeURIComponent(attendanceMonth)}`, token)
      .then((data) => {
        if (!active) return
        setPersonalAttendance(data.records)
        setAttendanceSummary(data.summary)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setPersonalAttendanceLoading(false)
      })

    return () => {
      active = false
    }
  }, [token, attendanceMonth])

  useEffect(() => {
    if (!selectedCourseId || !attendanceDate) return undefined

    let active = true
    const courseId = encodeURIComponent(selectedCourseId)
    const path =
      `/teacher/courses/${courseId}/students?attendance_date=` +
      encodeURIComponent(attendanceDate)
    apiRequest(path, token)
      .then((data) => {
        if (!active) return
        setAcademicYear(data.academic_year)
        setAttendanceRoster(
          data.students.map((student) => ({
            ...student,
            status: student.attendance_status || 'present',
            notes: student.attendance_notes || '',
          })),
        )
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setAttendanceLoading(false)
      })

    return () => {
      active = false
    }
  }, [token, selectedCourseId, attendanceDate])

  useEffect(() => {
    if (!selectedCourseId) return undefined

    let active = true
    apiRequest(`/teacher/courses/${encodeURIComponent(selectedCourseId)}/notes`, token)
      .then((notes) => {
        if (active) setCourseNotes(notes)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setNotesLoading(false)
      })

    return () => {
      active = false
    }
  }, [token, selectedCourseId])

  useEffect(() => {
    if (!showAttendanceHistory || !selectedCourseId || !attendanceHistoryMonth) {
      return undefined
    }

    let active = true
    const path =
      `/teacher/courses/${encodeURIComponent(selectedCourseId)}/attendance/history` +
      `?month=${encodeURIComponent(attendanceHistoryMonth)}`
    apiRequest(path, token)
      .then((data) => {
        if (active) setAttendanceHistory(data.records)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setHistoryLoading(false)
      })

    return () => {
      active = false
    }
  }, [token, selectedCourseId, attendanceHistoryMonth, showAttendanceHistory])

  const classNames = [...new Set(attendanceRoster.map((student) => student.class_name))]
    .filter(Boolean)
    .sort()
  const visibleRoster = attendanceRoster.filter(
    (student) => classFilter === 'all' || student.class_name === classFilter,
  )
  const visibleStudentIds = new Set(visibleRoster.map((student) => student.student_id))
  const visibleHistory = attendanceHistory.filter(
    (record) => classFilter === 'all' || record.class_name === classFilter,
  )
  const attendanceCounts = visibleRoster.reduce(
    (counts, student) => {
      counts[student.status] = (counts[student.status] || 0) + 1
      return counts
    },
    { present: 0, absent: 0, late: 0 },
  )
  const filteredPersonalAttendance = personalAttendance.filter(
    (record) =>
      !attendanceDay || String(record.attendance_date).slice(0, 10) === attendanceDay,
  )
  const paidSalary = salary.payments
    .filter((payment) => payment.status === 'paid')
    .reduce((total, payment) => total + Number(payment.net_amount), 0)
  const salaryStatus = dashboard?.salary_status?.status || 'not_recorded'
  const minAttendanceMonth = academicYear?.start_date?.slice(0, 7)
  const maxAttendanceMonth = getLocalDate().slice(0, 7)
  const maxAttendanceDate =
    academicYear?.end_date && academicYear.end_date < getLocalDate()
      ? academicYear.end_date
      : getLocalDate()

  function updateAttendance(studentId, field, value) {
    setAttendanceRoster((current) =>
      current.map((student) =>
        student.student_id === studentId ? { ...student, [field]: value } : student,
      ),
    )
  }

  function handleCourseChange(event) {
    setSelectedCourseId(event.target.value)
    setClassFilter('all')
    setAttendanceLoading(true)
    setNotesLoading(true)
    setShowAttendanceHistory(false)
  }

  async function refreshAttendanceRoster() {
    const path =
      `/teacher/courses/${encodeURIComponent(selectedCourseId)}/students?attendance_date=` +
      encodeURIComponent(attendanceDate)
    const data = await apiRequest(path, token)
    setAttendanceRoster(
      data.students.map((student) => ({
        ...student,
        status: student.attendance_status || 'present',
        notes: student.attendance_notes || '',
      })),
    )
  }

  async function handleSaveAttendance(event) {
    event.preventDefault()
    if (
      visibleRoster.length === 0 ||
      !window.confirm(`Save attendance for ${visibleRoster.length} students?`)
    ) {
      return
    }
    setAttendanceSaving(true)
    setFeedback(null)
    try {
      await apiRequest(`/teacher/courses/${selectedCourseId}/attendance`, token, {
        method: 'POST',
        body: JSON.stringify({
          attendance_date: attendanceDate,
          records: visibleRoster.map((student) => ({
            student_id: student.student_id,
            status: student.status,
            notes: student.notes,
          })),
        }),
      })
      await refreshAttendanceRoster()
      if (showAttendanceHistory) {
        setHistoryLoading(true)
        const path =
          `/teacher/courses/${encodeURIComponent(selectedCourseId)}/attendance/history` +
          `?month=${encodeURIComponent(attendanceHistoryMonth)}`
        const history = await apiRequest(path, token)
        setAttendanceHistory(history.records)
        setHistoryLoading(false)
      }
      setFeedback({ type: 'success', text: 'Student attendance saved.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setAttendanceSaving(false)
      setHistoryLoading(false)
    }
  }

  function handleMarkAllPresent() {
    setAttendanceRoster((current) =>
      current.map((student) =>
        visibleStudentIds.has(student.student_id)
          ? { ...student, status: 'present' }
          : student,
      ),
    )
  }

  async function handleUploadNote(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const body = new FormData()
    body.append('title', values.get('title'))
    body.append('description', values.get('description'))
    body.append('file', values.get('file'))
    setNoteUploading(true)
    setFeedback(null)
    try {
      const result = await apiRequest(
        `/teacher/courses/${selectedCourseId}/notes`,
        token,
        { method: 'POST', body },
      )
      setCourseNotes((current) => [result, ...current])
      setFeedback({ type: 'success', text: 'Course notes uploaded.' })
      form.reset()
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setNoteUploading(false)
    }
  }

  async function handleDownloadNote(note) {
    setFeedback(null)
    try {
      await downloadFile(
        `/teacher/notes/${note.id}/download`,
        token,
        note.original_filename,
      )
      const notes = await apiRequest(
        `/teacher/courses/${selectedCourseId}/notes`,
        token,
      )
      setCourseNotes(notes)
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  function startEditingNote(note) {
    setEditingNoteId(note.id)
    setEditingNoteTitle(note.title)
    setEditingNoteDescription(note.description || '')
  }

  async function handleUpdateNote(event, noteId) {
    event.preventDefault()
    setNoteSaving(true)
    setFeedback(null)
    try {
      const updatedNote = await apiRequest(`/teacher/notes/${noteId}`, token, {
        method: 'PATCH',
        body: JSON.stringify({
          title: editingNoteTitle,
          description: editingNoteDescription,
        }),
      })
      setCourseNotes((current) =>
        current.map((note) => (note.id === noteId ? updatedNote : note)),
      )
      setEditingNoteId(null)
      setFeedback({ type: 'success', text: 'Course note updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setNoteSaving(false)
    }
  }

  async function handleDeleteNote(note) {
    if (!window.confirm(`Delete "${note.title}"? This cannot be undone.`)) return
    setFeedback(null)
    try {
      await apiRequest(`/teacher/notes/${note.id}`, token, { method: 'DELETE' })
      setCourseNotes((current) => current.filter((item) => item.id !== note.id))
      setFeedback({ type: 'success', text: 'Course note deleted.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  function handleAttendanceMonthChange(event) {
    if (!event.target.value) return
    setAttendanceMonth(event.target.value)
    setAttendanceDay('')
    setPersonalAttendanceLoading(true)
  }

  function handleAttendanceDayChange(event) {
    const value = event.target.value
    setAttendanceDay(value)
    if (value) {
      setAttendanceMonth(value.slice(0, 7))
      setPersonalAttendanceLoading(true)
    }
  }

  const tabs = [
    ['overview', 'Overview'],
    ['my-attendance', 'My attendance'],
    ['my-salary', 'My salary'],
    ['student-attendance', 'Student attendance'],
    ['course-notes', 'Course notes'],
  ]

  return (
    <div className="admin-app teacher-app">
      <header className="topbar">
        <a className="brand" href="#teacher-top" aria-label="Teacher dashboard home">
          <span className="brand-mark small">SM</span>
          <span>
            <strong>School Management</strong>
            <small>Teacher portal</small>
          </span>
        </a>
        <button className="secondary-button" onClick={onLogout}>
          Sign out
        </button>
      </header>

      <main className="dashboard" id="teacher-top">
        <section className="welcome-panel teacher-welcome">
          <div>
            <p className="eyebrow">Teacher dashboard</p>
            <h1>{profile?.name || 'Welcome'}</h1>
            <p className="welcome-copy">
              {profile
                ? `${profile.designation} · ${profile.employee_number}`
                : 'View your records and manage your assigned courses.'}
            </p>
          </div>
          <div className="summary-cards teacher-summary-cards">
            <div className="summary-card">
              <span>Assigned courses</span>
              <strong>{courses.length}</strong>
            </div>
            <div className="summary-card">
              <span>Total students</span>
              <strong>{dashboard?.total_students || 0}</strong>
            </div>
            <div className="summary-card">
              <span>Today's classes</span>
              <strong>{dashboard?.todays_classes?.length || 0}</strong>
            </div>
            <div className="summary-card">
              <span>Attendance taken</span>
              <strong>{dashboard?.attendance_taken || 0}</strong>
            </div>
            <div className="summary-card">
              <span>Monthly attendance</span>
              <strong>{dashboard?.monthly_attendance?.percentage || 0}%</strong>
            </div>
            <div className="summary-card">
              <span>Salary status</span>
              <strong className="summary-status">
                {salaryStatus === 'not_recorded'
                  ? 'No record'
                  : salaryStatus.replace('_', ' ')}
              </strong>
            </div>
          </div>
        </section>

        <nav className="tabs" aria-label="Teacher sections">
          {tabs.map(([tab, label]) => (
            <button
              key={tab}
              className={activeTab === tab ? 'tab active' : 'tab'}
              aria-current={activeTab === tab ? 'page' : undefined}
              onClick={() => setActiveTab(tab)}
            >
              {label}
            </button>
          ))}
        </nav>

        {feedback && (
          <div className={`feedback ${feedback.type}`} role="status">
            {feedback.text}
          </div>
        )}

        {loading ? (
          <section className="panel">
            <p className="empty-state">Loading your teacher dashboard...</p>
          </section>
        ) : (
          <>
            {activeTab === 'overview' && (
              <>
                <section className="teacher-overview-top">
                  <div className="panel">
                    <div className="panel-heading">
                      <div>
                        <p className="eyebrow">Your timetable</p>
                        <h2>Today's schedule</h2>
                      </div>
                      <span className="count-pill">
                        {dashboard?.todays_classes?.length || 0} classes
                      </span>
                    </div>
                    {dashboard?.todays_classes?.length ? (
                      <div className="course-list">
                        {dashboard.todays_classes.map((item) => (
                          <article className="schedule-row" key={item.id}>
                            <span className="schedule-time">
                              {item.start_time}
                              <small>{item.end_time}</small>
                            </span>
                            <div>
                              <strong>{item.course_code} · {item.course_name}</strong>
                              <p>
                                {item.class_name || 'Class not set'}
                                {item.room ? ` · ${item.room}` : ''}
                              </p>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="empty-state">
                        No classes are scheduled for today.
                      </p>
                    )}
                  </div>
                  <div className="panel">
                    <div className="panel-heading">
                      <div>
                        <p className="eyebrow">Your courses</p>
                        <h2>Assigned courses</h2>
                      </div>
                    </div>
                    {courses.length === 0 ? (
                      <p className="empty-state">No courses are assigned to your account.</p>
                    ) : (
                      <div className="course-list">
                        {courses.map((course) => (
                          <article className="course-row" key={course.id}>
                            <span className="course-code">{course.course_code}</span>
                            <div>
                              <strong>{course.name}</strong>
                              <p>{course.description || 'No description'}</p>
                            </div>
                            <span className="row-id">#{course.id}</span>
                          </article>
                        ))}
                      </div>
                    )}
                  </div>
                </section>

                <section className="teacher-overview-bottom">
                  <div className="panel">
                    <div className="panel-heading">
                      <div>
                        <p className="eyebrow">Recent activity</p>
                        <h2>Recent activities</h2>
                      </div>
                    </div>
                    {dashboard?.recent_activities?.length ? (
                      <div className="activity-list">
                        {dashboard.recent_activities.map((activity, index) => (
                          <article
                            className="activity-row"
                            key={`${activity.activity_type}-${activity.activity_date}-${index}`}
                          >
                            <span className="activity-mark" />
                            <div>
                              <strong>{activity.title}</strong>
                              <p>{activity.activity_type} · {formatDateTime(activity.activity_date)}</p>
                            </div>
                          </article>
                        ))}
                      </div>
                    ) : (
                      <p className="empty-state">No recent course activity.</p>
                    )}
                  </div>
                  <div className="panel quick-actions">
                    <p className="eyebrow">Get started</p>
                    <h2>Quick actions</h2>
                    <button
                      className="primary-button"
                      onClick={() => setActiveTab('student-attendance')}
                    >
                      Take student attendance
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => setActiveTab('course-notes')}
                    >
                      Upload course notes
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => setActiveTab('my-attendance')}
                    >
                      View my attendance
                    </button>
                  </div>
                </section>
              </>
            )}

            {activeTab === 'my-attendance' && (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Personal records</p>
                    <h2>My attendance</h2>
                    <p className="muted">
                      {attendanceSummary.percentage}% attendance for{' '}
                      {attendanceMonth}
                    </p>
                  </div>
                  <span className="count-pill">
                    {attendanceSummary.total_days} days recorded
                  </span>
                </div>
                <div className="teacher-filters">
                  <label>
                    Month
                    <input
                      type="month"
                      required
                      value={attendanceMonth}
                      onChange={handleAttendanceMonthChange}
                    />
                  </label>
                  <label>
                    Daily attendance
                    <input
                      type="date"
                      value={attendanceDay}
                      max={getLocalDate()}
                      onChange={handleAttendanceDayChange}
                    />
                  </label>
                </div>
                <div className="attendance-summary">
                  {[
                    ['Present', attendanceSummary.present_days],
                    ['Absent', attendanceSummary.absent_days],
                    ['Late', attendanceSummary.late_days],
                    ['On leave', attendanceSummary.leave_days],
                  ].map(([label, count]) => (
                    <article key={label}>
                      <span>{label}</span>
                      <strong>{count}</strong>
                    </article>
                  ))}
                </div>
                {personalAttendanceLoading ? (
                  <p className="empty-state">Loading attendance history...</p>
                ) : filteredPersonalAttendance.length === 0 ? (
                  <p className="empty-state">No attendance records for this period.</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Check-in time</th>
                          <th>Check-out time</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredPersonalAttendance.map((entry) => (
                          <tr key={entry.attendance_date}>
                            <td>{formatDate(entry.attendance_date)}</td>
                            <td>{entry.check_in || '-'}</td>
                            <td>{entry.check_out || '-'}</td>
                            <td>
                              <span className={`attendance-pill ${entry.status}`}>
                                {entry.status.replace('_', ' ')}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {activeTab === 'my-salary' && (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Payroll records</p>
                    <h2>My salary</h2>
                    <p className="muted">Salary details are read-only.</p>
                  </div>
                  <span className="count-pill">{salary.payments.length} periods</span>
                </div>
                <div className="salary-highlight">
                  <span>Monthly base salary</span>
                  <strong>{formatCurrency(salary.base_salary)}</strong>
                  <small>{formatCurrency(paidSalary)} paid across listed periods</small>
                </div>
                {salary.payments.length === 0 ? (
                  <p className="empty-state">No salary payments have been recorded.</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Period</th>
                          <th>Gross amount</th>
                          <th>Allowances</th>
                          <th>Deductions</th>
                          <th>Net amount</th>
                          <th>Payment status</th>
                          <th>Paid at</th>
                          <th>Payslip</th>
                        </tr>
                      </thead>
                      <tbody>
                        {salary.payments.map((payment) => (
                          <tr key={payment.id}>
                            <td>{formatDate(payment.pay_period)}</td>
                            <td>{formatCurrency(payment.gross_amount)}</td>
                            <td>{formatCurrency(payment.allowances)}</td>
                            <td>{formatCurrency(payment.deductions)}</td>
                            <td>{formatCurrency(payment.net_amount)}</td>
                            <td>
                              <span className={`status-pill ${payment.status}`}>
                                {payment.status}
                              </span>
                            </td>
                            <td>{payment.paid_at ? formatDateTime(payment.paid_at) : '-'}</td>
                            <td>
                              <button
                                type="button"
                                className="secondary-button compact-button"
                                onClick={() => setSelectedPayslip(payment)}
                              >
                                View payslip
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {activeTab === 'student-attendance' && (
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Course register</p>
                    <h2>Take student attendance</h2>
                  </div>
                  <span className="count-pill">{visibleRoster.length} students</span>
                </div>
                <div className="teacher-filters attendance-filters">
                  <label>
                    Assigned course
                    <select
                      value={selectedCourseId}
                      onChange={handleCourseChange}
                      disabled={courses.length === 0}
                    >
                      {courses.length === 0 ? (
                        <option value="">No assigned courses</option>
                      ) : (
                        courses.map((course) => (
                          <option key={course.id} value={course.id}>
                            {course.course_code} - {course.name}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <label>
                    Class
                    <select
                      value={classFilter}
                      onChange={(event) => setClassFilter(event.target.value)}
                    >
                      <option value="all">All classes</option>
                      {classNames.map((className) => (
                        <option key={className} value={className}>
                          {className}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Attendance date
                    <input
                      type="date"
                      required
                      min={academicYear?.start_date}
                      max={maxAttendanceDate}
                      value={attendanceDate}
                      onChange={(event) => {
                        if (!event.target.value) return
                        setAttendanceLoading(true)
                        setAttendanceDate(event.target.value)
                      }}
                    />
                  </label>
                </div>
                <div className="attendance-summary">
                  {[
                    ['Total students', visibleRoster.length],
                    ['Present', attendanceCounts.present],
                    ['Absent', attendanceCounts.absent],
                    ['Late', attendanceCounts.late],
                  ].map(([label, count]) => (
                    <article key={label}>
                      <span>{label}</span>
                      <strong>{count}</strong>
                    </article>
                  ))}
                </div>
                {courses.length === 0 ? (
                  <p className="empty-state">No courses are assigned to your account.</p>
                ) : attendanceLoading ? (
                  <p className="empty-state">Loading enrolled students...</p>
                ) : visibleRoster.length === 0 ? (
                  <p className="empty-state">
                    No students are enrolled in this class and course for the selected date.
                  </p>
                ) : (
                  <form onSubmit={handleSaveAttendance}>
                    <div className="attendance-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={handleMarkAllPresent}
                      >
                        Mark all present
                      </button>
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Student ID</th>
                            <th>Student name</th>
                            <th>Roll number</th>
                            <th>Attendance status</th>
                            <th>Remarks</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleRoster.map((student) => (
                            <tr key={student.student_id}>
                              <td>{student.student_id}</td>
                              <td>
                                <strong>{student.name}</strong>
                                <small>{student.username}</small>
                              </td>
                              <td>{student.admission_number}</td>
                              <td>
                                <select
                                  aria-label={`Attendance for ${student.name}`}
                                  value={student.status}
                                  onChange={(event) =>
                                    updateAttendance(
                                      student.student_id,
                                      'status',
                                      event.target.value,
                                    )
                                  }
                                >
                                  {STUDENT_ATTENDANCE_STATUSES.map((status) => (
                                    <option key={status.value} value={status.value}>
                                      {status.label}
                                    </option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                <input
                                  aria-label={`Remarks for ${student.name}`}
                                  value={student.notes}
                                  maxLength="500"
                                  onChange={(event) =>
                                    updateAttendance(
                                      student.student_id,
                                      'notes',
                                      event.target.value,
                                    )
                                  }
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div className="attendance-actions">
                      <button
                        className="primary-button teacher-submit"
                        disabled={attendanceSaving || !attendanceDate}
                      >
                        {attendanceSaving ? 'Saving attendance...' : 'Save attendance'}
                      </button>
                    </div>
                  </form>
                )}
                <div className="attendance-history-toggle">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={courses.length === 0}
                    onClick={() => {
                      setShowAttendanceHistory((current) => !current)
                      setHistoryLoading(true)
                    }}
                  >
                    {showAttendanceHistory ? 'Hide attendance history' : 'View attendance history'}
                  </button>
                </div>
                {showAttendanceHistory && (
                  <section className="history-panel">
                    <div className="panel-heading">
                      <div>
                        <p className="eyebrow">Saved course registers</p>
                        <h2>Attendance history</h2>
                      </div>
                      <label className="month-filter">
                        Month
                        <input
                          type="month"
                          required
                          value={attendanceHistoryMonth}
                          min={minAttendanceMonth}
                          max={maxAttendanceMonth}
                          onChange={(event) => {
                            if (!event.target.value) return
                            setHistoryLoading(true)
                            setAttendanceHistoryMonth(event.target.value)
                          }}
                        />
                      </label>
                    </div>
                    {historyLoading ? (
                      <p className="empty-state">Loading attendance history...</p>
                    ) : visibleHistory.length === 0 ? (
                      <p className="empty-state">No saved attendance for this month.</p>
                    ) : (
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Date</th>
                              <th>Student ID</th>
                              <th>Student name</th>
                              <th>Roll number</th>
                              <th>Status</th>
                              <th>Remarks</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visibleHistory.map((record) => (
                              <tr key={`${record.attendance_date}-${record.student_id}`}>
                                <td>{formatDate(record.attendance_date)}</td>
                                <td>{record.student_id}</td>
                                <td>{record.name}</td>
                                <td>{record.admission_number}</td>
                                <td>
                                  <span className={`attendance-pill ${record.status}`}>
                                    {record.status}
                                  </span>
                                </td>
                                <td>{record.notes || '-'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </section>
                )}
              </section>
            )}

            {activeTab === 'course-notes' && (
              <section className="content-grid teacher-notes-grid">
                <div className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Course materials</p>
                      <h2>Upload notes</h2>
                    </div>
                  </div>
                  <label className="standalone-label">
                    Assigned course
                    <select
                      value={selectedCourseId}
                      onChange={handleCourseChange}
                      disabled={courses.length === 0}
                    >
                      {courses.length === 0 ? (
                        <option value="">No assigned courses</option>
                      ) : (
                        courses.map((course) => (
                          <option key={course.id} value={course.id}>
                            {course.course_code} - {course.name}
                          </option>
                        ))
                      )}
                    </select>
                  </label>
                  <form className="form-stack note-upload-form" onSubmit={handleUploadNote}>
                    <label>
                      Note title
                      <input name="title" maxLength="150" required />
                    </label>
                    <label>
                      Description <span className="optional">(optional)</span>
                      <textarea name="description" rows="3" maxLength="2000" />
                    </label>
                    <label>
                      File
                      <input
                        name="file"
                        type="file"
                        accept=".pdf,.doc,.docx,.ppt,.pptx"
                        required
                      />
                    </label>
                    <p className="muted">
                      PDF, DOC, DOCX, PPT, or PPTX files up to 15 MB.
                    </p>
                    <button
                      className="primary-button"
                      disabled={noteUploading || courses.length === 0}
                    >
                      {noteUploading ? 'Uploading...' : 'Upload course notes'}
                    </button>
                  </form>
                </div>
                <div className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Shared materials</p>
                      <h2>Course notes library</h2>
                    </div>
                    <span className="count-pill">{courseNotes.length} files</span>
                  </div>
                  {notesLoading ? (
                    <p className="empty-state">Loading course notes...</p>
                  ) : courseNotes.length === 0 ? (
                    <p className="empty-state">No notes have been uploaded for this course.</p>
                  ) : (
                    <div className="note-library">
                      {courseNotes.map((note) => (
                        <article className="note-card" key={note.id}>
                          {editingNoteId === note.id ? (
                            <form
                              className="form-stack"
                              onSubmit={(event) => handleUpdateNote(event, note.id)}
                            >
                              <label>
                                Note title
                                <input
                                  value={editingNoteTitle}
                                  maxLength="150"
                                  required
                                  onChange={(event) =>
                                    setEditingNoteTitle(event.target.value)
                                  }
                                />
                              </label>
                              <label>
                                Description
                                <textarea
                                  value={editingNoteDescription}
                                  rows="3"
                                  maxLength="2000"
                                  onChange={(event) =>
                                    setEditingNoteDescription(event.target.value)
                                  }
                                />
                              </label>
                              <div className="note-actions">
                                <button
                                  className="primary-button"
                                  disabled={noteSaving}
                                >
                                  {noteSaving ? 'Saving...' : 'Save changes'}
                                </button>
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => setEditingNoteId(null)}
                                >
                                  Cancel
                                </button>
                              </div>
                            </form>
                          ) : (
                            <>
                              <div className="note-card-heading">
                                <span className="note-file-mark">
                                  {note.original_filename.split('.').pop()?.toUpperCase()}
                                </span>
                                <div>
                                  <strong>{note.title}</strong>
                                  <p>{note.original_filename}</p>
                                </div>
                              </div>
                              {note.description && (
                                <p className="note-description">{note.description}</p>
                              )}
                              <div className="note-meta">
                                <span>Uploaded {formatDate(note.uploaded_at)}</span>
                                <span>
                                  {Number(note.download_count || 0)} downloads
                                </span>
                                <span>
                                  {(Number(note.file_size) / (1024 * 1024)).toFixed(2)} MB
                                </span>
                              </div>
                              <div className="note-actions">
                                <button
                                  type="button"
                                  className="primary-button"
                                  onClick={() => handleDownloadNote(note)}
                                >
                                  Download
                                </button>
                                <button
                                  type="button"
                                  className="secondary-button"
                                  onClick={() => startEditingNote(note)}
                                >
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="danger-button"
                                  onClick={() => handleDeleteNote(note)}
                                >
                                  Delete
                                </button>
                              </div>
                            </>
                          )}
                        </article>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            )}
          </>
        )}

        {selectedPayslip && (
          <div
            className="modal-backdrop"
            role="presentation"
            onClick={() => setSelectedPayslip(null)}
          >
            <section
              className="payslip-card"
              role="dialog"
              aria-modal="true"
              aria-labelledby="payslip-title"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Salary statement</p>
                  <h2 id="payslip-title">Payslip · {formatDate(selectedPayslip.pay_period)}</h2>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => setSelectedPayslip(null)}
                >
                  Close
                </button>
              </div>
              <dl className="payslip-details">
                <div><dt>Teacher</dt><dd>{profile?.name}</dd></div>
                <div><dt>Employee number</dt><dd>{profile?.employee_number}</dd></div>
                <div><dt>Gross salary</dt><dd>{formatCurrency(selectedPayslip.gross_amount)}</dd></div>
                <div><dt>Allowances</dt><dd>{formatCurrency(selectedPayslip.allowances)}</dd></div>
                <div><dt>Deductions</dt><dd>{formatCurrency(selectedPayslip.deductions)}</dd></div>
                <div><dt>Net salary</dt><dd>{formatCurrency(selectedPayslip.net_amount)}</dd></div>
                <div><dt>Payment status</dt><dd>{selectedPayslip.status}</dd></div>
                <div><dt>Paid at</dt><dd>{formatDateTime(selectedPayslip.paid_at)}</dd></div>
                {selectedPayslip.notes && (
                  <div><dt>Notes</dt><dd>{selectedPayslip.notes}</dd></div>
                )}
              </dl>
              <button
                type="button"
                className="primary-button"
                onClick={() => window.print()}
              >
                Print payslip
              </button>
            </section>
          </div>
        )}
      </main>
    </div>
  )
}

export default TeacherDashboard
