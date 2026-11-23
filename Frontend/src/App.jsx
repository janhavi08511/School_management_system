import { useCallback, useEffect, useMemo, useState } from 'react'
import './Admin.css'
import { apiRequest } from './api'
import TeacherDashboard from './TeacherDashboard'
import StudentDashboard from './StudentDashboard'

const PAYMENT_METHODS = ['cash', 'card', 'bank_transfer', 'online', 'other']
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const ATTENDANCE_STATUSES = [
  { value: 'present', label: 'Present' },
  { value: 'absent', label: 'Absent' },
  { value: 'late', label: 'Late' },
  { value: 'half_day', label: 'Half day' },
  { value: 'on_leave', label: 'On leave' },
]

function getLocalDate() {
  const today = new Date()
  const year = today.getFullYear()
  const month = String(today.getMonth() + 1).padStart(2, '0')
  const day = String(today.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function getDateYearsAgo(years) {
  const today = new Date()
  const year = today.getFullYear() - years
  const month = today.getMonth()
  const day = Math.min(
    today.getDate(),
    new Date(year, month + 1, 0).getDate(),
  )
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function getNextAdmissionNumber(students) {
  let highestNumber = 0
  let prefix = 'STU-'
  let numberWidth = 4

  for (const student of students) {
    const match = String(student.admission_number || '').match(/^(.*?)(\d+)$/)
    if (!match) continue

    const number = Number(match[2])
    if (Number.isSafeInteger(number) && number > highestNumber) {
      highestNumber = number
      prefix = match[1] || 'STU-'
      numberWidth = Math.max(4, match[2].length)
    }
  }

  return `${prefix}${String(highestNumber + 1).padStart(numberWidth, '0')}`
}

function getClassKey(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const match = text.match(/^(\d+)/)
  return match ? match[1] : text.toLowerCase()
}

function normalizeDirectoryResponse(response) {
  const roles = ['students', 'teachers', 'non_teaching_staff']
  const data = {}
  const pagination = {}

  for (const role of roles) {
    const section = response?.[role]
    data[role] = Array.isArray(section) ? section : (section?.data || [])
    pagination[role] = section?.pagination || {
      page: 1,
      page_size: 20,
      total_records: data[role].length,
      total_pages: 1,
      has_next: false,
      has_previous: false,
    }
  }

  return { data, pagination }
}

function PaginationControls({ pagination, onPageChange, disabled = false }) {
  if (!pagination) return null

  const { page = 1, total_pages = 1, total_records = 0, page_size = 20 } = pagination
  const firstRecord = total_records === 0 ? 0 : (page - 1) * page_size + 1
  const lastRecord = Math.min(page * page_size, total_records)

  return (
    <div
      className="pagination-controls"
      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginTop: '16px' }}
    >
      <span className="muted">
        Showing {firstRecord}-{lastRecord} of {total_records}
      </span>
      <div className="pagination-actions" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          type="button"
          className="secondary-button"
          onClick={() => onPageChange(page - 1)}
          disabled={disabled || page <= 1}
        >
          Previous
        </button>
        <span className="pagination-page">Page {page} of {Math.max(total_pages, 1)}</span>
        <button
          type="button"
          className="secondary-button"
          onClick={() => onPageChange(page + 1)}
          disabled={disabled || page >= total_pages}
        >
          Next
        </button>
      </div>
    </div>
  )
}

async function loadAdminData(token) {
  // Keep login lightweight. Large/secondary modules are fetched when opened.
  const [courses, students, payments, academicYears] = await Promise.all([
    apiRequest('/admin/courses?page=1&page_size=100', token),
    apiRequest('/admin/students?page=1&page_size=100', token),
    apiRequest('/admin/payments?page=1&page_size=10', token),
    apiRequest('/admin/academic-years', token),
  ])

  return { courses, students, payments, academicYears }
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleDateString()
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function getPercentage(value, total) {
  return total > 0 ? Math.round((value / total) * 100) : 0
}

function App() {
  const [token, setToken] = useState('')
  const [userRole, setUserRole] = useState('')
  const [activeTab, setActiveTab] = useState('analytics')
  const [activeDirectoryRole, setActiveDirectoryRole] = useState('students')
  const [courses, setCourses] = useState([])
  const [courseCatalog, setCourseCatalog] = useState([])
  const [courseCatalogPagination, setCourseCatalogPagination] = useState(null)
  const [courseCatalogSearch, setCourseCatalogSearch] = useState('')
  const [courseCatalogSearchQuery, setCourseCatalogSearchQuery] = useState('')
  const [courseClassFilter, setCourseClassFilter] = useState('all')
  const [courseCatalogPage, setCourseCatalogPage] = useState(1)
  const [courseCatalogPageSize] = useState(5)
  const [studentClassName, setStudentClassName] = useState('')
  const [students, setStudents] = useState([])
  const [studentPagination, setStudentPagination] = useState(null)
  const [payments, setPayments] = useState([])
  const [paymentTotalCount, setPaymentTotalCount] = useState(0)
  const [paymentHistorySearch, setPaymentHistorySearch] = useState('')
  const [paymentHistorySearchQuery, setPaymentHistorySearchQuery] = useState('')
  const [paymentHistoryClassFilter, setPaymentHistoryClassFilter] = useState('all')
  const [paymentHistoryMethodFilter, setPaymentHistoryMethodFilter] = useState('all')
  const [paymentHistoryPage, setPaymentHistoryPage] = useState(1)
  const [paymentHistoryPagination, setPaymentHistoryPagination] = useState(null)
  const [paymentHistoryLoading, setPaymentHistoryLoading] = useState(false)
  const [paymentHistoryError, setPaymentHistoryError] = useState('')
  const [paymentHistoryRefreshVersion, setPaymentHistoryRefreshVersion] = useState(0)
  const [academicYears, setAcademicYears] = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [analyticsLoading, setAnalyticsLoading] = useState(false)
  const [analyticsLoaded, setAnalyticsLoaded] = useState(false)
  const [analyticsError, setAnalyticsError] = useState('')
  const [analyticsRequestVersion, setAnalyticsRequestVersion] = useState(0)
  const [schedules, setSchedules] = useState([])
  const [selectedScheduleDay, setSelectedScheduleDay] = useState(0)
  const [scheduleDayCounts, setScheduleDayCounts] = useState({})
  const [schedulePagination, setSchedulePagination] = useState(null)
  const [schedulePage, setSchedulePage] = useState(1)
  const [schedulePageSize] = useState(10)
  const [scheduleRefreshVersion, setScheduleRefreshVersion] = useState(0)
  const [dashboard, setDashboard] = useState(null)
  const [dashboardLoaded, setDashboardLoaded] = useState(false)
  const [feeTypes, setFeeTypes] = useState([])
  const [feeTypesLoading, setFeeTypesLoading] = useState(false)
  const [feeTypesError, setFeeTypesError] = useState('')
  const [feeTypesRefreshVersion, setFeeTypesRefreshVersion] = useState(0)
  const [feeStudents, setFeeStudents] = useState([])
  const [feeStudentSearch, setFeeStudentSearch] = useState('')
  const [feeStudentSearchQuery, setFeeStudentSearchQuery] = useState('')
  const [feeStudentPage, setFeeStudentPage] = useState(1)
  const [feeStudentPagination, setFeeStudentPagination] = useState(null)
  const [feeStudentLoading, setFeeStudentLoading] = useState(false)
  const [feeStudentError, setFeeStudentError] = useState('')
  const [feeStudentRefreshVersion, setFeeStudentRefreshVersion] = useState(0)
  const [feeAssignmentStudent, setFeeAssignmentStudent] = useState(null)
  const [feeAssignmentFeeType, setFeeAssignmentFeeType] = useState('')
  const [feeStudentBillingMode, setFeeStudentBillingMode] = useState('payment')
  const [feeClassOptions, setFeeClassOptions] = useState([])
  const [feeReferencesLoading, setFeeReferencesLoading] = useState(false)
  const [feeReferencesError, setFeeReferencesError] = useState('')
  const [feeReferencesRefreshVersion, setFeeReferencesRefreshVersion] = useState(0)
  const [feeInvoices, setFeeInvoices] = useState([])
  const [feeInvoicePagination, setFeeInvoicePagination] = useState(null)
  const [feeInvoiceSummary, setFeeInvoiceSummary] = useState(null)
  const [feeInvoiceSearch, setFeeInvoiceSearch] = useState('')
  const [feeInvoiceSearchQuery, setFeeInvoiceSearchQuery] = useState('')
  const [feeInvoicePage, setFeeInvoicePage] = useState(1)
  const [feeInvoicePageSize] = useState(10)
  const [feeInvoiceLoading, setFeeInvoiceLoading] = useState(false)
  const [feeInvoiceError, setFeeInvoiceError] = useState('')
  const [feeInvoiceRefreshVersion, setFeeInvoiceRefreshVersion] = useState(0)
  const [classFeeInvoiceClass, setClassFeeInvoiceClass] = useState('')
  const [classFeeTypeId, setClassFeeTypeId] = useState('')
  const [payroll, setPayroll] = useState([])
  const [payrollPagination, setPayrollPagination] = useState(null)
  const [payrollPage, setPayrollPage] = useState(1)
  const [payrollPageSize] = useState(25)
  const [payrollSearch, setPayrollSearch] = useState('')
  const [payrollSearchQuery, setPayrollSearchQuery] = useState('')
  const [payrollSummary, setPayrollSummary] = useState(null)
  const [performance, setPerformance] = useState([])
  const [performanceStudentOptions, setPerformanceStudentOptions] = useState([])
  const [performanceStudentSearch, setPerformanceStudentSearch] = useState('')
  const [performanceStudentSearchQuery, setPerformanceStudentSearchQuery] = useState('')
  const [events, setEvents] = useState([])
  const [selectedPayrollMonth, setSelectedPayrollMonth] = useState(getLocalDate().slice(0, 7))
  const [peopleSearch, setPeopleSearch] = useState('')
  const [studentClassFilter, setStudentClassFilter] = useState('all')
  const [studentCourseFilter, setStudentCourseFilter] = useState('all')
  const [studentStatusFilter, setStudentStatusFilter] = useState('all')
  const [editingUser, setEditingUser] = useState(null)
  const [editingStudent, setEditingStudent] = useState(null)
  const [editingStaff, setEditingStaff] = useState(null)
  const [studentProfile, setStudentProfile] = useState(null)
  const [selectedReceipt, setSelectedReceipt] = useState(null)
  const [selectedInvoice, setSelectedInvoice] = useState(null)
  const [invoicePayments, setInvoicePayments] = useState([])
  const [selectedCourse, setSelectedCourse] = useState(null)
  const [courseEnrollments, setCourseEnrollments] = useState([])
  const [enrollmentStudents, setEnrollmentStudents] = useState([])
  const [enrollmentStudentSearch, setEnrollmentStudentSearch] = useState('')
  const [enrollmentStudentSearchLoading, setEnrollmentStudentSearchLoading] = useState(false)
  const [paymentStudents, setPaymentStudents] = useState([])
  const [paymentStudentId, setPaymentStudentId] = useState('')
  const [paymentStudentSearch, setPaymentStudentSearch] = useState('')
  const [paymentStudentSearchQuery, setPaymentStudentSearchQuery] = useState('')
  const [paymentStudentClassFilter, setPaymentStudentClassFilter] = useState('all')
  const [paymentStudentStatusFilter, setPaymentStudentStatusFilter] = useState('all')
  const [paymentStudentClasses, setPaymentStudentClasses] = useState([])
  const [paymentStudentLoading, setPaymentStudentLoading] = useState(false)
  const [paymentStudentError, setPaymentStudentError] = useState('')
  const [paymentStudentRefreshVersion, setPaymentStudentRefreshVersion] = useState(0)
  const [feeStatusFilter, setFeeStatusFilter] = useState('all')
  const [feeClassFilter, setFeeClassFilter] = useState('all')
  const [performanceClassFilter, setPerformanceClassFilter] = useState('all')
  const [performanceCourseFilter, setPerformanceCourseFilter] = useState('all')
  const [performanceStudentFilter, setPerformanceStudentFilter] = useState('all')
  const [attendanceRoleFilter, setAttendanceRoleFilter] = useState('all')
  const [attendanceReport, setAttendanceReport] = useState(null)
  const [attendanceReportLoading, setAttendanceReportLoading] = useState(true)
  const [feeLoading, setFeeLoading] = useState(false)
  const [payrollLoading, setPayrollLoading] = useState(false)
  const [performanceLoading, setPerformanceLoading] = useState(false)
  const [eventLoading, setEventLoading] = useState(false)
  const [invoicePaymentMethod, setInvoicePaymentMethod] = useState('cash')
  const [directory, setDirectory] = useState({
    students: [],
    teachers: [],
    non_teaching_staff: [],
  })
  const [directoryPagination, setDirectoryPagination] = useState({
    students: null,
    teachers: null,
    non_teaching_staff: null,
  })
  const [directoryPages, setDirectoryPages] = useState({
    students: 1,
    teachers: 1,
    non_teaching_staff: 1,
  })
  const [directoryPageSize] = useState(20)
  const [directoryLoading, setDirectoryLoading] = useState(false)
  const [attendanceRows, setAttendanceRows] = useState([])
  const [attendanceSearch, setAttendanceSearch] = useState('')
  const [attendanceSearchQuery, setAttendanceSearchQuery] = useState('')
  const [attendancePage, setAttendancePage] = useState(1)
  const [attendancePagination, setAttendancePagination] = useState(null)
  const [attendancePageSize] = useState(25)
  const [attendanceReportSearch, setAttendanceReportSearch] = useState('')
  const [attendanceReportSearchQuery, setAttendanceReportSearchQuery] = useState('')
  const [attendanceReportPage, setAttendanceReportPage] = useState(1)
  const [attendanceReportPageSize] = useState(25)
  const [attendanceDate, setAttendanceDate] = useState(getLocalDate)
  const [feedback, setFeedback] = useState(null)
  const [loginLoading, setLoginLoading] = useState(false)
  const [courseLoading, setCourseLoading] = useState(false)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [userLoading, setUserLoading] = useState(false)
  const [paymentLoading, setPaymentLoading] = useState(false)
  const [attendanceLoading, setAttendanceLoading] = useState(true)
  const [attendanceSubmitting, setAttendanceSubmitting] = useState(false)
  const [newUserRole, setNewUserRole] = useState('student')

  const applyAdminData = useCallback((data) => {
    setCourses(Array.isArray(data.courses) ? data.courses : (data.courses?.data || []))
    const studentResponse = data.students || []
    setStudents(Array.isArray(studentResponse) ? studentResponse : (studentResponse.data || []))
    setStudentPagination(Array.isArray(studentResponse) ? null : (studentResponse.pagination || null))
    const paymentResponse = data.payments
    setPayments(
      Array.isArray(paymentResponse)
        ? paymentResponse
        : (paymentResponse?.data || []),
    )
    setPaymentHistoryPagination(
      Array.isArray(paymentResponse)
        ? null
        : (paymentResponse?.pagination || null),
    )
    setPaymentTotalCount(
      Array.isArray(paymentResponse)
        ? paymentResponse.length
        : (paymentResponse?.pagination?.total_records || 0),
    )
    setAcademicYears(data.academicYears)
    const normalizedDirectory = normalizeDirectoryResponse(data.directory)
    setDirectory(normalizedDirectory.data)
    setDirectoryPagination(normalizedDirectory.pagination)
    setSchedules(Array.isArray(data.schedules) ? data.schedules : (data.schedules?.data || []))
    setScheduleDayCounts(data.schedules?.day_counts || {})
    setSchedulePagination(data.schedules?.pagination || null)
    // Dashboard, users, payroll, performance, directory and events are lazy-loaded.
  }, [])

  useEffect(() => {
    if (!token || userRole !== 'admin') return undefined

    let active = true
    loadAdminData(token)
      .then((data) => {
        if (!active) return
        applyAdminData(data)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })

    return () => {
      active = false
    }
  }, [applyAdminData, token, userRole])

  // Load the expensive analytics endpoint only when the Analytics tab is opened.
  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'analytics' || analyticsLoaded) {
      return undefined
    }

    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) {
        setAnalyticsLoading(true)
        setAnalyticsError('')
      }
    }, 0)

    apiRequest('/admin/analytics', token)
      .then((result) => {
        if (!active) return
        setAnalytics(result)
        setAnalyticsLoaded(true)
      })
      .catch((error) => {
        if (!active) return
        setAnalyticsError(error.message || 'Unable to load analytics.')
      })
      .finally(() => {
        if (active) setAnalyticsLoading(false)
      })

    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab, analyticsLoaded, analyticsRequestVersion])

  useEffect(() => {
    const handle = setTimeout(() => {
      setPaymentStudentSearchQuery(paymentStudentSearch.trim())
      setPaymentStudentRefreshVersion((version) => version + 1)
    }, 300)
    return () => clearTimeout(handle)
  }, [paymentStudentSearch])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'payment') return undefined

    let active = true
    const params = new URLSearchParams()
    if (paymentStudentSearchQuery) params.set('search', paymentStudentSearchQuery)
    if (paymentStudentClassFilter !== 'all') {
      params.set('class_name', paymentStudentClassFilter)
    }
    if (paymentStudentStatusFilter !== 'all') {
      params.set('student_status', paymentStudentStatusFilter)
    }

    const request = setTimeout(() => {
      if (!active) return

      setPaymentStudentLoading(true)
      setPaymentStudentError('')
      params.set('page', '1')
      params.set('page_size', '50')
      apiRequest(`/admin/students?${params.toString()}`, token)
        .then((response) => {
          if (!active) return
          const rows = Array.isArray(response) ? response : (response.data || [])
          setPaymentStudents(rows)
          setPaymentStudentId((currentId) =>
            rows.some(
              (student) =>
                String(student.id) === currentId && Number(student.balance) > 0,
            )
              ? currentId
              : '',
          )
          if (
            !paymentStudentSearchQuery &&
            paymentStudentClassFilter === 'all' &&
            paymentStudentStatusFilter === 'all'
          ) {
            setPaymentStudentClasses(
              [...new Set(
                rows
                  .map((student) => String(student.class_name ?? '').trim())
                  .filter(Boolean),
              )].sort((left, right) =>
                left.localeCompare(right, undefined, { numeric: true }),
              ),
            )
          }
        })
        .catch((error) => {
          if (!active) return
          setPaymentStudents([])
          setPaymentStudentError(error.message || 'Unable to load students.')
        })
        .finally(() => {
          if (active) setPaymentStudentLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [
    token,
    userRole,
    activeTab,
    paymentStudentSearchQuery,
    paymentStudentClassFilter,
    paymentStudentStatusFilter,
    paymentStudentRefreshVersion,
  ])

  useEffect(() => {
    const handle = setTimeout(() => {
      setPaymentHistorySearchQuery(paymentHistorySearch.trim())
      setPaymentHistoryPage(1)
      setPaymentHistoryRefreshVersion((version) => version + 1)
    }, 300)
    return () => clearTimeout(handle)
  }, [paymentHistorySearch])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'history') return undefined

    let active = true
    const params = new URLSearchParams({
      page: String(paymentHistoryPage),
      page_size: '10',
      search: paymentHistorySearchQuery,
    })
    if (paymentHistoryClassFilter !== 'all') {
      params.set('class_name', paymentHistoryClassFilter)
    }
    if (paymentHistoryMethodFilter !== 'all') {
      params.set('payment_method', paymentHistoryMethodFilter)
    }

    const request = setTimeout(() => {
      if (!active) return

      setPaymentHistoryLoading(true)
      setPaymentHistoryError('')
      apiRequest(`/admin/payments?${params.toString()}`, token)
        .then((response) => {
          if (!active) return
          const rows = Array.isArray(response) ? response : (response?.data || [])
          setPayments((current) =>
            paymentHistoryPage === 1 ? rows : [...current, ...rows],
          )
          setPaymentHistoryPagination(
            Array.isArray(response) ? null : (response?.pagination || null),
          )
          if (
            !paymentHistorySearchQuery &&
            paymentHistoryClassFilter === 'all' &&
            paymentHistoryMethodFilter === 'all'
          ) {
            setPaymentTotalCount(
              Array.isArray(response)
                ? response.length
                : (response?.pagination?.total_records || 0),
            )
          }
        })
        .catch((error) => {
          if (!active) return
          setPaymentHistoryError(error.message || 'Unable to load payment history.')
        })
        .finally(() => {
          if (active) setPaymentHistoryLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [
    token,
    userRole,
    activeTab,
    paymentHistoryPage,
    paymentHistorySearchQuery,
    paymentHistoryClassFilter,
    paymentHistoryMethodFilter,
    paymentHistoryRefreshVersion,
  ])

  useEffect(() => {
    const handle = setTimeout(() => {
      setFeeInvoiceSearchQuery(feeInvoiceSearch.trim())
      setFeeInvoicePage(1)
      setFeeInvoiceRefreshVersion((version) => version + 1)
    }, 300)
    return () => clearTimeout(handle)
  }, [feeInvoiceSearch])

  useEffect(() => {
    const handle = setTimeout(() => {
      setFeeStudentSearchQuery(feeStudentSearch.trim())
      setFeeStudentPage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [feeStudentSearch])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'fees') return undefined

    let active = true
    const request = setTimeout(() => {
      if (!active) return
      setFeeTypesLoading(true)
      setFeeTypesError('')
      apiRequest('/admin/fee-types', token)
        .then((response) => {
          if (!active) return
          setFeeTypes(Array.isArray(response) ? response : [])
        })
        .catch((error) => {
          if (!active) return
          setFeeTypes([])
          setFeeTypesError(error.message || 'Unable to load fee structures.')
        })
        .finally(() => {
          if (active) setFeeTypesLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [token, userRole, activeTab, feeTypesRefreshVersion])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'fees') return undefined

    let active = true
    const request = setTimeout(() => {
      if (!active) return
      setFeeReferencesLoading(true)
      setFeeReferencesError('')
      Promise.all([
        apiRequest('/admin/fee-classes', token).then((response) => {
          if (!Array.isArray(response)) throw new Error('Class options returned an invalid response.')
          if (active) setFeeClassOptions(response)
        }),
        apiRequest('/admin/academic-years', token).then((response) => {
          const years = Array.isArray(response)
            ? response
            : (Array.isArray(response?.data) ? response.data : null)
          if (!years) throw new Error('Academic years returned an invalid response.')
          if (active) setAcademicYears(years)
        }),
      ])
        .catch((error) => {
          if (!active) return
          setFeeReferencesError(error.message || 'Unable to load fee assignment options.')
        })
        .finally(() => {
          if (active) setFeeReferencesLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [token, userRole, activeTab, feeReferencesRefreshVersion])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'fees') return undefined

    let active = true
    const params = new URLSearchParams({
      page: String(feeStudentPage),
      page_size: '20',
    })
    if (feeStudentSearchQuery) params.set('search', feeStudentSearchQuery)
    const request = setTimeout(() => {
      if (!active) return
      setFeeStudentLoading(true)
      setFeeStudentError('')
      apiRequest(`/admin/fee-students?${params.toString()}`, token)
        .then((response) => {
          if (!active) return
          if (!Array.isArray(response?.data)) {
            throw new Error('Student options returned an invalid response.')
          }
          setFeeStudents(response.data)
          setFeeStudentPagination(response.pagination || null)
        })
        .catch((error) => {
          if (!active) return
          setFeeStudents([])
          setFeeStudentPagination(null)
          setFeeStudentError(error.message || 'Unable to load fee student options.')
        })
        .finally(() => {
          if (active) setFeeStudentLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [
    token,
    userRole,
    activeTab,
    feeStudentPage,
    feeStudentSearchQuery,
    feeStudentRefreshVersion,
  ])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'fees') return undefined

    let active = true
    const params = new URLSearchParams({
      page: String(feeInvoicePage),
      page_size: String(feeInvoicePageSize),
    })
    if (feeInvoiceSearchQuery) params.set('search', feeInvoiceSearchQuery)
    if (feeStatusFilter !== 'all') params.set('payment_status', feeStatusFilter)
    if (feeClassFilter !== 'all') params.set('class_name', feeClassFilter)

    const request = setTimeout(() => {
      if (!active) return

      setFeeInvoiceLoading(true)
      setFeeInvoiceError('')
      apiRequest(`/admin/fee-invoices?${params.toString()}`, token)
        .then((response) => {
          if (!active) return
          setFeeInvoices(
            Array.isArray(response)
              ? response
              : (Array.isArray(response?.data) ? response.data : []),
          )
          setFeeInvoicePagination(
            Array.isArray(response) ? null : (response?.pagination || null),
          )
          setFeeInvoiceSummary(
            Array.isArray(response) ? null : (response?.summary || null),
          )
        })
        .catch((error) => {
          if (!active) return
          setFeeInvoiceError(error.message || 'Unable to load invoices.')
        })
        .finally(() => {
          if (active) setFeeInvoiceLoading(false)
        })
    }, 0)

    return () => {
      active = false
      clearTimeout(request)
    }
  }, [
    token,
    userRole,
    activeTab,
    feeInvoicePage,
    feeInvoicePageSize,
    feeInvoiceSearchQuery,
    feeStatusFilter,
    feeClassFilter,
    feeInvoiceRefreshVersion,
  ])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'directory') return undefined

    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) setDirectoryLoading(true)
    }, 0)

    const query = new URLSearchParams({
      student_page: String(directoryPages.students),
      teacher_page: String(directoryPages.teachers),
      non_teaching_page: String(directoryPages.non_teaching_staff),
      page_size: String(directoryPageSize),
    })

    apiRequest(`/admin/directory?${query.toString()}`, token)
      .then((response) => {
        if (!active) return
        const normalized = normalizeDirectoryResponse(response)
        setDirectory(normalized.data)
        setDirectoryPagination(normalized.pagination)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setDirectoryLoading(false)
      })

    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab, directoryPages, directoryPageSize])

  useEffect(() => {
    const handle = setTimeout(() => {
      setAttendanceSearchQuery(attendanceSearch.trim())
      setAttendancePage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [attendanceSearch])

  useEffect(() => {
    const handle = setTimeout(() => {
      setCourseCatalogSearchQuery(courseCatalogSearch.trim())
      setCourseCatalogPage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [courseCatalogSearch])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'courses') return undefined

    let active = true
    const params = new URLSearchParams({
      page: String(courseCatalogPage),
      page_size: String(courseCatalogPageSize),
      search: courseCatalogSearchQuery,
    })
    if (courseClassFilter !== 'all') params.set('class_name', courseClassFilter)

    apiRequest(`/admin/courses?${params.toString()}`, token)
      .then((response) => {
        if (!active) return
        setCourseCatalog(Array.isArray(response) ? response : (response.data || []))
        setCourseCatalogPagination(response.pagination || null)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })

    return () => {
      active = false
    }
  }, [
    token,
    userRole,
    activeTab,
    courseCatalogPage,
    courseCatalogPageSize,
    courseCatalogSearchQuery,
    courseClassFilter,
  ])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'courses') return undefined

    let active = true
    const params = new URLSearchParams({
      day_of_week: String(selectedScheduleDay),
      page: String(schedulePage),
      page_size: String(schedulePageSize),
    })
    apiRequest(`/admin/schedules?${params.toString()}`, token)
      .then((response) => {
        if (!active) return
        setSchedules(Array.isArray(response) ? response : (response.data || []))
        setScheduleDayCounts(response.day_counts || {})
        setSchedulePagination(response.pagination || null)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })

    return () => {
      active = false
    }
  }, [
    token,
    userRole,
    activeTab,
    selectedScheduleDay,
    schedulePage,
    schedulePageSize,
    scheduleRefreshVersion,
  ])

  useEffect(() => {
    const handle = setTimeout(() => {
      setAttendanceReportSearchQuery(attendanceReportSearch.trim())
      setAttendanceReportPage(1)
    }, 300)
    return () => clearTimeout(handle)
  }, [attendanceReportSearch])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'attendance') return undefined

    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) setAttendanceLoading(true)
    }, 0)
    const params = new URLSearchParams({
      attendance_date: attendanceDate,
      page: String(attendancePage),
      page_size: String(attendancePageSize),
      search: attendanceSearchQuery,
    })
    if (attendanceRoleFilter !== 'all') params.set('staff_type', attendanceRoleFilter)

    apiRequest(`/admin/staff-attendance?${params.toString()}`, token)
      .then((response) => {
        if (!active) return
        // Supports the paginated response and the legacy array during backend rollout.
        setAttendanceRows(Array.isArray(response) ? response : (response.data || []))
        setAttendancePagination(response.pagination || null)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setAttendanceLoading(false)
      })

    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab, attendanceDate, attendanceRoleFilter, attendancePage, attendancePageSize, attendanceSearchQuery])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'attendance') return undefined

    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) setAttendanceReportLoading(true)
    }, 0)
    const month = attendanceDate.slice(0, 7)
    const reportParams = new URLSearchParams({
      month,
      page: String(attendanceReportPage),
      page_size: String(attendanceReportPageSize),
      search: attendanceReportSearchQuery,
    })
    if (attendanceRoleFilter !== 'all') reportParams.set('staff_type', attendanceRoleFilter)
    apiRequest(`/admin/staff-attendance/report?${reportParams.toString()}`, token)
      .then((report) => {
        if (active) setAttendanceReport(report)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setAttendanceReportLoading(false)
      })

    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab, attendanceDate, attendanceRoleFilter, attendanceReportPage, attendanceReportPageSize, attendanceReportSearchQuery])

  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'payroll') return undefined

    let active = true
    const params = new URLSearchParams({
      month: selectedPayrollMonth,
      page: String(payrollPage),
      page_size: String(payrollPageSize),
    })
    if (payrollSearchQuery) params.set('search', payrollSearchQuery)
    const loadingHandle = setTimeout(() => {
      if (active) setPayrollLoading(true)
    }, 0)
    apiRequest(`/admin/payroll?${params.toString()}`, token)
      .then((response) => {
        if (!active) return
        setPayroll(Array.isArray(response) ? response : (response.data || []))
        setPayrollPagination(response.pagination || null)
        setPayrollSummary(response.summary || null)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
      .finally(() => {
        if (active) setPayrollLoading(false)
      })

    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab, selectedPayrollMonth, payrollPage, payrollPageSize, payrollSearchQuery])

  useEffect(() => {
    const handle = setTimeout(() => {
      setPayrollSearchQuery(payrollSearch.trim())
      setPayrollPage(1)
    }, 350)
    return () => clearTimeout(handle)
  }, [payrollSearch])

  // Fetch dashboard summaries only after the dashboard tab is opened.
  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'analytics' || dashboardLoaded) return undefined
    let active = true
    apiRequest('/admin/dashboard', token)
      .then((nextDashboard) => {
        if (!active) return
        setDashboard(nextDashboard)
        setDashboardLoaded(true)
      })
      .catch((error) => {
        if (active) setFeedback({ type: 'error', text: error.message })
      })
    return () => { active = false }
  }, [token, userRole, activeTab, dashboardLoaded])

  // Events are fetched only when the Events module is opened.
  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'events') return undefined
    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) setEventLoading(true)
    }, 0)
    apiRequest('/admin/events?upcoming_only=true', token)
      .then((result) => { if (active) setEvents(result) })
      .catch((error) => { if (active) setFeedback({ type: 'error', text: error.message }) })
      .finally(() => { if (active) setEventLoading(false) })
    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab])

  useEffect(() => {
    const handle = setTimeout(() => setPerformanceStudentSearchQuery(performanceStudentSearch.trim()), 350)
    return () => clearTimeout(handle)
  }, [performanceStudentSearch])

  // Performance records load once when the Performance module is opened.
  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'performance') return undefined
    let active = true
    const loadingHandle = setTimeout(() => {
      if (active) setPerformanceLoading(true)
    }, 0)
    apiRequest('/admin/performance?page=1&page_size=50', token)
      .then((response) => {
        if (active) setPerformance(Array.isArray(response) ? response : (response.data || []))
      })
      .catch((error) => { if (active) setFeedback({ type: 'error', text: error.message }) })
      .finally(() => { if (active) setPerformanceLoading(false) })
    return () => {
      clearTimeout(loadingHandle)
      active = false
    }
  }, [token, userRole, activeTab])

  // Search only the student selector; do not refetch the performance table per keystroke.
  useEffect(() => {
    if (!token || userRole !== 'admin' || activeTab !== 'performance') return undefined
    let active = true
    const params = new URLSearchParams({ page: '1', page_size: '50' })
    if (performanceStudentSearchQuery) params.set('search', performanceStudentSearchQuery)
    apiRequest(`/admin/students?${params.toString()}`, token)
      .then((response) => {
        if (active) setPerformanceStudentOptions(Array.isArray(response) ? response : (response.data || []))
      })
      .catch((error) => { if (active) setFeedback({ type: 'error', text: error.message }) })
    return () => { active = false }
  }, [token, userRole, activeTab, performanceStudentSearchQuery])

  async function handleLogin(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setLoginLoading(true)
    setFeedback(null)

    try {
      const result = await apiRequest('/auth/login', '', {
        method: 'POST',
        body: JSON.stringify({
          username: values.get('username'),
          password: values.get('password'),
        }),
      })
      const roles = result.user?.roles || []
      const role = roles.includes('admin')
        ? 'admin'
        : roles.includes('teacher')
          ? 'teacher'
          : roles.includes('student')
            ? 'student'
            : ''
      if (!role) {
        throw new Error('This page is available to administrators, teachers, and students.')
      }
      if (role === 'admin') setAttendanceLoading(true)
      setUserRole(role)
      setToken(result.access_token)
      setFeedback({ type: 'success', text: 'Signed in successfully.' })
      form.reset()
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setLoginLoading(false)
    }
  }

  async function handleCreateCourse(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setCourseLoading(true)
    setFeedback(null)

    try {
      const result = await apiRequest('/admin/courses', token, {
        method: 'POST',
        body: JSON.stringify({
          course_code: values.get('course_code'),
          name: values.get('name'),
          description: values.get('description'),
          class_name: values.get('class_name') || null,
          duration_months: values.get('duration_months')
            ? Number(values.get('duration_months'))
            : null,
          academic_year_id: values.get('course_academic_year_id')
            ? Number(values.get('course_academic_year_id'))
            : null,
          teacher_id: values.get('course_teacher_id')
            ? Number(values.get('course_teacher_id'))
            : null,
        }),
      })
      setCourses((current) =>
        [...current, result].sort((a, b) => a.course_code.localeCompare(b.course_code)),
      )
      setCourseCatalog((current) =>
        [...current, result].sort((a, b) => a.course_code.localeCompare(b.course_code)),
      )
      setAnalytics((current) =>
        current ? { ...current, courses: current.courses + 1 } : current,
      )
      setFeedback({
        type: 'success',
        text: `${result.course_code} was created (ID ${result.id}).`,
      })
      form.reset()
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setCourseLoading(false)
    }
  }

  async function handleCreateSchedule(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setScheduleLoading(true)
    setFeedback(null)
    try {
      await apiRequest('/admin/schedules', token, {
        method: 'POST',
        body: JSON.stringify({
          course_id: Number(values.get('course_id')),
          day_of_week: Number(values.get('day_of_week')),
          start_time: values.get('start_time'),
          end_time: values.get('end_time'),
          class_name: values.get('class_name'),
          room: values.get('room'),
        }),
      })
      setSelectedScheduleDay(Number(values.get('day_of_week')))
      setSchedulePage(1)
      setScheduleRefreshVersion((version) => version + 1)
      setFeedback({ type: 'success', text: 'Course schedule added.' })
      form.reset()
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setScheduleLoading(false)
    }
  }

  async function handleCreateUser(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const courseIds = Array.from(
      form.querySelectorAll(
        'input[name="course_ids"]:checked, select[name="course_ids"] option:checked',
      ),
      (option) => Number(option.value),
    )
    const admissionNumber = getNextAdmissionNumber(students)

    if (newUserRole === 'student') {
      const dateOfBirth = String(values.get('date_of_birth') || '')
      const admissionDate = String(values.get('admission_date') || '')
      if (!dateOfBirth || dateOfBirth > getDateYearsAgo(5)) {
        setFeedback({
          type: 'error',
          text: 'Students must be at least 5 years old.',
        })
        form.querySelector('[name="date_of_birth"]')?.focus()
        return
      }
      if (
        !admissionDate ||
        admissionDate > getLocalDate() ||
        admissionDate < dateOfBirth
      ) {
        setFeedback({
          type: 'error',
          text: 'Admission date must be today or earlier and cannot precede the date of birth.',
        })
        form.querySelector('[name="admission_date"]')?.focus()
        return
      }
      if (courseIds.length === 0) {
        setFeedback({
          type: 'error',
          text: 'Select at least one course for the student.',
        })
        form.querySelector('input[name="course_ids"]')?.focus()
        return
      }
    }

    const body = {
      username: values.get('username'),
      password: values.get('password'),
      role: newUserRole,
      first_name: values.get('first_name'),
      last_name: values.get('last_name'),
      email: values.get('email'),
      phone: values.get('phone'),
    }

    if (newUserRole === 'student') {
      body.student = {
        admission_number: admissionNumber,
        date_of_birth: values.get('date_of_birth'),
        gender: values.get('gender') || null,
        admission_date: values.get('admission_date'),
        course_ids: courseIds,
        academic_year_id: Number(values.get('academic_year_id')),
        address: values.get('address'),
        parent_guardian_name: values.get('parent_guardian_name'),
        parent_contact: values.get('parent_contact'),
        fee_amount: values.get('fee_amount'),
        class_name: values.get('class_name'),
      }
    } else if (newUserRole === 'teacher') {
      body.teacher = {
        joining_date: values.get('joining_date'),
        course_ids: courseIds,
        education: values.get('education'),
        experience_years: values.get('experience_years') || '0',
        department: values.get('department'),
        address: values.get('staff_address'),
        salary: values.get('salary'),
      }
    } else {
      body.non_teaching_staff = {
        salary: values.get('salary'),
        work: values.get('work'),
        shift: values.get('shift'),
        joining_date: values.get('staff_joining_date') || null,
        department: values.get('department'),
        address: values.get('staff_address'),
      }
    }

    setUserLoading(true)
    setFeedback(null)
    try {
      const result = await apiRequest('/users/', token, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      const photo = values.get('profile_photo')
      if (photo instanceof File && photo.size > 0) {
        const upload = new FormData()
        upload.append('file', photo)
        await apiRequest(`/admin/users/${result.id}/photo`, token, {
          method: 'POST',
          body: upload,
        })
      }
      const data = await loadAdminData(token)
      applyAdminData(data)
      setFeedback({
        type: 'success',
        text: `User created. User ID: ${result.id}${result.employee_number ? ` | Employee number: ${result.employee_number}` : ''}.`,
      })
      form.reset()
      setNewUserRole('student')
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setUserLoading(false)
    }
  }

  async function handleSaveUser(event) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    setUserLoading(true)
    try {
      await apiRequest(`/admin/users/${editingUser.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({
          first_name: values.get('first_name'),
          last_name: values.get('last_name'),
          email: values.get('email'),
          phone: values.get('phone'),
        }),
      })
      await refreshAdminData()
      setEditingUser(null)
      setFeedback({ type: 'success', text: 'User details updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setUserLoading(false)
    }
  }

  async function handleDeleteUser(user) {
    if (!window.confirm(`Permanently delete ${user.name}? Historical records may prevent deletion.`)) {
      return
    }
    try {
      await apiRequest(`/admin/users/${user.id}`, token, { method: 'DELETE' })
      await refreshAdminData()
      setFeedback({ type: 'success', text: 'User deleted.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleSaveStudent(event) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    try {
      await apiRequest(`/admin/students/${editingStudent.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({
          first_name: values.get('first_name'),
          last_name: values.get('last_name'),
          email: values.get('email'),
          phone: values.get('phone'),
          date_of_birth: values.get('date_of_birth') || null,
          gender: values.get('gender'),
          address: values.get('address'),
          class_name: values.get('class_name'),
          admission_date: values.get('admission_date'),
          parent_guardian_name: values.get('parent_guardian_name'),
          parent_contact: values.get('parent_contact'),
          fee_amount: values.get('fee_amount'),
          status: values.get('status'),
        }),
      })
      await refreshAdminData()
      setEditingStudent(null)
      setFeedback({ type: 'success', text: 'Student profile updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleSaveStaff(event) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    try {
      await apiRequest(`/admin/staff/${editingStaff.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({
          first_name: values.get('first_name'),
          last_name: values.get('last_name'),
          email: values.get('email'),
          phone: values.get('phone'),
          designation: values.get('designation'),
          hire_date: values.get('hire_date'),
          education: values.get('education'),
          experience_years: values.get('experience_years') || '0',
          department: values.get('department'),
          address: values.get('address'),
          base_salary: values.get('base_salary'),
          shift: values.get('shift'),
          status: values.get('status'),
        }),
      })
      await refreshAdminData()
      setEditingStaff(null)
      setFeedback({ type: 'success', text: 'Staff profile updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleOpenStudentProfile(studentId) {
    try {
      setStudentProfile(
        await apiRequest(`/admin/students/${studentId}/profile`, token),
      )
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleSaveCourse(event) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    try {
      await apiRequest(`/admin/courses/${selectedCourse.id}`, token, {
        method: 'PUT',
        body: JSON.stringify({
          course_code: values.get('course_code'),
          name: values.get('name'),
          description: values.get('description'),
          class_name: values.get('class_name') || null,
          duration_months: values.get('duration_months')
            ? Number(values.get('duration_months'))
            : null,
          academic_year_id: values.get('academic_year_id')
            ? Number(values.get('academic_year_id'))
            : null,
          teacher_id: values.get('teacher_id')
            ? Number(values.get('teacher_id'))
            : null,
        }),
      })
      await refreshAdminData()
      setSelectedCourse(null)
      setFeedback({ type: 'success', text: 'Course details updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleDeleteCourse(course) {
    if (!window.confirm(`Delete ${course.course_code} - ${course.name}?`)) return
    try {
      await apiRequest(`/admin/courses/${course.id}`, token, { method: 'DELETE' })
      await refreshAdminData()
      setFeedback({ type: 'success', text: 'Course deleted.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleLoadEnrollments(course) {
    setSelectedCourse(course)
    setCourseEnrollments([])
    setEnrollmentStudents([])
    setEnrollmentStudentSearch('')
    try {
      const year = academicYears.find((item) => item.is_current) || academicYears[0]
      const query = year ? `?academic_year_id=${year.id}` : ''
      const studentParams = new URLSearchParams({ page: '1', page_size: '20' })
      if (course.class_name) studentParams.set('class_name', course.class_name)
      const [courseDetails, enrollments, studentResponse] = await Promise.all([
        apiRequest(`/admin/courses/${course.id}`, token),
        apiRequest(`/admin/courses/${course.id}/enrollments${query}`, token),
        apiRequest(`/admin/enrollment-students?${studentParams.toString()}`, token),
      ])
      setSelectedCourse(courseDetails)
      setCourseEnrollments(enrollments)
      setEnrollmentStudents(studentResponse.data || [])
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleSearchEnrollmentStudents(event) {
    event.preventDefault()
    if (!selectedCourse) return
    setEnrollmentStudentSearchLoading(true)
    try {
      const params = new URLSearchParams({
        page: '1',
        page_size: '20',
        search: enrollmentStudentSearch.trim(),
      })
      if (selectedCourse.class_name) {
        params.set('class_name', selectedCourse.class_name)
      }
      const response = await apiRequest(
        `/admin/enrollment-students?${params.toString()}`,
        token,
      )
      setEnrollmentStudents(response.data || [])
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setEnrollmentStudentSearchLoading(false)
    }
  }

  async function handleEnrollStudent(event) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    try {
      await apiRequest(
        `/admin/courses/${selectedCourse.id}/enrollments?student_id=${values.get('student_id')}&academic_year_id=${values.get('academic_year_id')}`,
        token,
        { method: 'POST' },
      )
      await handleLoadEnrollments(selectedCourse)
      await refreshAdminData()
      setFeedback({ type: 'success', text: 'Student enrolled in the course.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleWithdrawStudent(enrollment) {
    if (!window.confirm(`Withdraw ${enrollment.student_name} from this course?`)) return
    try {
      await apiRequest(
        `/admin/courses/${selectedCourse.id}/enrollments/${enrollment.student_id}?academic_year_id=${enrollment.academic_year_id}`,
        token,
        { method: 'DELETE' },
      )
      await handleLoadEnrollments(selectedCourse)
      setFeedback({ type: 'success', text: 'Student withdrawn from the course.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleCreateFeeType(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setFeeLoading(true)
    try {
      const createdFeeType = await apiRequest('/admin/fee-types', token, {
        method: 'POST',
        body: JSON.stringify({
          name: values.get('name'),
          description: values.get('description'),
          amount: values.get('amount'),
          class_name: values.get('class_name') || null,
          academic_year_id: values.get('academic_year_id')
            ? Number(values.get('academic_year_id'))
            : null,
        }),
      })
      setFeeAssignmentFeeType(String(createdFeeType.id))
      setFeeTypesRefreshVersion((version) => version + 1)
      form.reset()
      setFeedback({
        type: 'success',
        text: 'Fee structure created and selected for individual student assignment.',
      })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setFeeLoading(false)
    }
  }

  async function handleAssignFee(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setFeeLoading(true)
    try {
      await apiRequest('/admin/fee-invoices', token, {
        method: 'POST',
        body: JSON.stringify({
          student_id: Number(values.get('student_id')),
          fee_type_id: Number(values.get('fee_type_id')),
          academic_year_id: Number(values.get('academic_year_id')),
          amount: values.get('amount') || null,
          due_date: values.get('due_date'),
        }),
      })
      setFeeInvoicePage(1)
      setFeeInvoiceRefreshVersion((version) => version + 1)
      form.reset()
      setFeeAssignmentStudent(null)
      setFeeAssignmentFeeType('')
      setFeedback({ type: 'success', text: 'Fee assigned to the student.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setFeeLoading(false)
    }
  }

  async function handleRecordExtraFeePayment(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setFeeLoading(true)
    try {
      const payment = await apiRequest('/admin/fee-invoices/student-payment', token, {
        method: 'POST',
        body: JSON.stringify({
          student_id: Number(values.get('student_id')),
          fee_type_id: Number(values.get('fee_type_id')),
          academic_year_id: Number(values.get('academic_year_id')),
          amount: values.get('amount'),
          payment_method: values.get('payment_method'),
          transaction_reference: values.get('transaction_reference') || null,
          notes: values.get('notes') || null,
          invoice_due_date: values.get('invoice_due_date') || null,
        }),
      })
      setFeeInvoicePage(1)
      setFeeInvoiceRefreshVersion((version) => version + 1)
      setFeedback({
        type: 'success',
        text: `${payment.invoice_created ? 'Invoice created and payment recorded.' : 'Payment recorded.'} Remaining balance: ${formatCurrency(payment.remaining_balance)}.`,
      })
      form.elements.amount.value = ''
      form.elements.transaction_reference.value = ''
      form.elements.notes.value = ''
      await handleReceipt(payment.id)
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setFeeLoading(false)
    }
  }

  async function handleAssignClassFees(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    const className = String(values.get('class_name') || '')
    if (
      !window.confirm(
        `Create an individual invoice for every eligible active student in class ${className}? Existing invoices for this fee structure and academic year will be skipped.`,
      )
    ) {
      return
    }

    setFeeLoading(true)
    try {
      const result = await apiRequest('/admin/fee-invoices/class', token, {
        method: 'POST',
        body: JSON.stringify({
          class_name: className,
          fee_type_id: Number(values.get('fee_type_id')),
          academic_year_id: Number(values.get('academic_year_id')),
          amount: values.get('amount') || null,
          due_date: values.get('due_date'),
        }),
      })
      setFeeInvoicePage(1)
      setFeeInvoiceRefreshVersion((version) => version + 1)
      form.reset()
      setClassFeeInvoiceClass('')
      setClassFeeTypeId('')
      setFeedback({
        type: 'success',
        text: result.created_count
          ? `Created ${result.created_count} individual invoice(s) for active students in class ${result.class_name}. Existing invoices were skipped.`
          : `No new invoices were created for class ${result.class_name}. Eligible students may already have this fee for the selected year.`,
      })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setFeeLoading(false)
    }
  }

  async function handlePayInvoice(invoice) {
    const amount = window.prompt(
      `Amount to pay (remaining ${formatCurrency(invoice.pending_amount)}):`,
      invoice.pending_amount,
    )
    if (!amount) return
    try {
      const payment = await apiRequest(`/admin/fee-invoices/${invoice.id}/payments`, token, {
        method: 'POST',
        body: JSON.stringify({ amount, payment_method: invoicePaymentMethod }),
      })
      await handleReceipt(payment.id)
      setFeeInvoicePage(1)
      setFeeInvoiceRefreshVersion((version) => version + 1)
      setFeedback({ type: 'success', text: 'Invoice payment recorded.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleReceipt(paymentId) {
    try {
      setSelectedReceipt(
        await apiRequest(`/admin/fee-payments/${paymentId}/receipt`, token),
      )
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleLoadInvoicePayments(invoice) {
    try {
      setSelectedInvoice(invoice)
      setInvoicePayments(
        await apiRequest(`/admin/fee-invoices/${invoice.id}/payments`, token),
      )
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleGeneratePayroll() {
    setPayrollLoading(true)
    try {
      await apiRequest(
        `/admin/payroll/generate?month=${encodeURIComponent(selectedPayrollMonth)}`,
        token,
        { method: 'POST' },
      )
      const response = await apiRequest(
        `/admin/payroll?month=${encodeURIComponent(selectedPayrollMonth)}&page=${payrollPage}&page_size=${payrollPageSize}&search=${encodeURIComponent(payrollSearchQuery)}`,
        token,
      )
      setPayroll(response.data || [])
      setPayrollPagination(response.pagination || null)
      setPayrollSummary(response.summary || null)
      setDashboardLoaded(false)
      setFeedback({ type: 'success', text: `Payroll generated for ${selectedPayrollMonth}.` })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setPayrollLoading(false)
    }
  }

  async function handleEditPayroll(payment) {
    const allowances = window.prompt('Allowances:', payment.allowances)
    if (allowances === null) return
    const deductions = window.prompt('Deductions:', payment.deductions)
    if (deductions === null) return
    try {
      await apiRequest(`/admin/payroll/${payment.id}`, token, {
        method: 'PATCH',
        body: JSON.stringify({ allowances, deductions }),
      })
      const refreshed = await apiRequest(`/admin/payroll?month=${encodeURIComponent(selectedPayrollMonth)}&page=${payrollPage}&page_size=${payrollPageSize}&search=${encodeURIComponent(payrollSearchQuery)}`, token)
      setPayroll(refreshed.data || [])
      setPayrollPagination(refreshed.pagination || null)
      setPayrollSummary(refreshed.summary || null)
      setDashboardLoaded(false)
      setFeedback({ type: 'success', text: 'Payroll details updated.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleMarkSalaryPaid(payment) {
    if (!window.confirm(`Record ${formatCurrency(payment.net_amount)} paid to ${payment.employee_name}?`)) {
      return
    }
    try {
      await apiRequest(`/admin/payroll/${payment.id}/pay`, token, { method: 'POST' })
      const refreshed = await apiRequest(`/admin/payroll?month=${encodeURIComponent(selectedPayrollMonth)}&page=${payrollPage}&page_size=${payrollPageSize}&search=${encodeURIComponent(payrollSearchQuery)}`, token)
      setPayroll(refreshed.data || [])
      setPayrollPagination(refreshed.pagination || null)
      setPayrollSummary(refreshed.summary || null)
      setDashboardLoaded(false)
      setFeedback({ type: 'success', text: 'Salary payment recorded.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleCreateAssessment(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setPerformanceLoading(true)
    try {
      await apiRequest('/admin/performance', token, {
        method: 'POST',
        body: JSON.stringify({
          student_id: Number(values.get('student_id')),
          course_id: Number(values.get('course_id')),
          academic_year_id: Number(values.get('academic_year_id')),
          exam_name: values.get('exam_name'),
          marks_obtained: values.get('marks_obtained'),
          total_marks: values.get('total_marks'),
        }),
      })
      const refreshedPerformance = await apiRequest('/admin/performance?page=1&page_size=50', token)
      setPerformance(Array.isArray(refreshedPerformance) ? refreshedPerformance : (refreshedPerformance.data || []))
      setDashboardLoaded(false)
      form.reset()
      setFeedback({ type: 'success', text: 'Assessment result saved.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setPerformanceLoading(false)
    }
  }

  async function handleDeleteAssessment(assessmentId) {
    if (!window.confirm('Delete this performance record?')) return
    try {
      await apiRequest(`/admin/performance/${assessmentId}`, token, { method: 'DELETE' })
      const refreshedPerformance = await apiRequest('/admin/performance?page=1&page_size=50', token)
      setPerformance(Array.isArray(refreshedPerformance) ? refreshedPerformance : (refreshedPerformance.data || []))
      setDashboardLoaded(false)
      setFeedback({ type: 'success', text: 'Performance record deleted.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function handleCreateEvent(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setEventLoading(true)
    try {
      await apiRequest('/admin/events', token, {
        method: 'POST',
        body: JSON.stringify({
          title: values.get('title'),
          description: values.get('description'),
          starts_at: new Date(values.get('starts_at')).toISOString(),
          ends_at: values.get('ends_at')
            ? new Date(values.get('ends_at')).toISOString()
            : null,
        }),
      })
      await refreshDashboard()
      form.reset()
      setFeedback({ type: 'success', text: 'Upcoming event added.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setEventLoading(false)
    }
  }

  async function handleDeleteEvent(eventId) {
    if (!window.confirm('Delete this school event?')) return
    try {
      await apiRequest(`/admin/events/${eventId}`, token, { method: 'DELETE' })
      await refreshDashboard()
      setFeedback({ type: 'success', text: 'Event deleted.' })
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    }
  }

  async function refreshDashboard() {
    const [nextDashboard, nextEvents] = await Promise.all([
      apiRequest('/admin/dashboard', token),
      apiRequest('/admin/events?upcoming_only=true', token),
    ])
    setDashboard(nextDashboard)
    setEvents(nextEvents)
    setDashboardLoaded(true)
  }

  async function refreshAdminData() {
    const data = await loadAdminData(token)
    applyAdminData(data)
    return data
  }

  async function handleRecordAttendance(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setAttendanceSubmitting(true)
    setFeedback(null)

    try {
      await apiRequest('/admin/staff-attendance', token, {
        method: 'POST',
        body: JSON.stringify({
          staff_id: Number(values.get('staff_id')),
          attendance_date: values.get('attendance_date'),
          status: values.get('status'),
          check_in: values.get('check_in') || null,
          check_out: values.get('check_out') || null,
          notes: values.get('notes'),
        }),
      })
      const attendanceParams = new URLSearchParams({
        attendance_date: attendanceDate,
        page: String(attendancePage),
        page_size: String(attendancePageSize),
        search: attendanceSearchQuery,
      })
      if (attendanceRoleFilter !== 'all') attendanceParams.set('staff_type', attendanceRoleFilter)
      const attendanceResponse = await apiRequest(
        `/admin/staff-attendance?${attendanceParams.toString()}`,
        token,
      )
      setAttendanceRows(Array.isArray(attendanceResponse) ? attendanceResponse : (attendanceResponse.data || []))
      setAttendancePagination(attendanceResponse.pagination || null)
      const attendanceRoleQuery =
        attendanceRoleFilter === 'all'
          ? ''
          : `&staff_type=${encodeURIComponent(attendanceRoleFilter)}`
      setAttendanceReport(
        await apiRequest(
          `/admin/staff-attendance/report?month=${encodeURIComponent(attendanceDate.slice(0, 7))}${attendanceRoleQuery}`,
          token,
        ),
      )
      setFeedback({ type: 'success', text: 'Staff attendance saved.' })
      form.elements.staff_id.value = ''
      form.elements.status.value = 'present'
      form.elements.check_in.value = ''
      form.elements.check_out.value = ''
      form.elements.notes.value = ''
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setAttendanceSubmitting(false)
    }
  }

  async function handleCreatePayment(event) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setPaymentLoading(true)
    setFeedback(null)

    try {
      const result = await apiRequest('/admin/payments', token, {
        method: 'POST',
        body: JSON.stringify({
          student_id: Number(values.get('student_id')),
          amount: values.get('amount'),
          payment_method: values.get('payment_method'),
          transaction_reference: values.get('transaction_reference'),
          notes: values.get('notes'),
        }),
      })
      const data = await loadAdminData(token)
      applyAdminData(data)
      setPaymentStudentId('')
      setPaymentStudentLoading(true)
      setPaymentStudentRefreshVersion((version) => version + 1)
      setFeedback({
        type: 'success',
        text: `Payment ${result.id} recorded. Remaining balance: ${formatCurrency(result.remaining_balance)}.`,
      })
      form.reset()
    } catch (error) {
      setFeedback({ type: 'error', text: error.message })
    } finally {
      setPaymentLoading(false)
    }
  }

  function handleLogout() {
    setToken('')
    setUserRole('')
    setCourses([])
    setStudents([])
    setPayments([])
    setPaymentTotalCount(0)
    setPaymentHistoryPagination(null)
    setFeeTypes([])
    setFeeTypesError('')
    setFeeStudents([])
    setFeeStudentPagination(null)
    setFeeStudentSearch('')
    setFeeStudentSearchQuery('')
    setFeeStudentPage(1)
    setFeeAssignmentStudent(null)
    setFeeClassOptions([])
    setFeeReferencesError('')
    setFeeInvoices([])
    setFeeInvoicePagination(null)
    setFeeInvoiceSummary(null)
    setAcademicYears([])
    setAnalytics(null)
    setAnalyticsLoading(false)
    setAnalyticsLoaded(false)
    setAnalyticsError('')
    setAnalyticsRequestVersion(0)
    setDashboard(null)
    setDashboardLoaded(false)
    setPayroll([])
    setPayrollPagination(null)
    setPayrollSummary(null)
    setSchedules([])
    setStudentPagination(null)
    setDirectory({ students: [], teachers: [], non_teaching_staff: [] })
    setDirectoryPagination({ students: null, teachers: null, non_teaching_staff: null })
    setDirectoryPages({ students: 1, teachers: 1, non_teaching_staff: 1 })
    setAttendanceRows([])
    setFeedback(null)
  }

  const studentCount = studentPagination?.total_records ?? students.length
  const outstandingCount = useMemo(
    () => dashboard?.metrics?.students_with_balance ?? students.filter((student) => Number(student.balance) > 0).length,
    [students, dashboard],
  )
  const paymentHistoryClasses = useMemo(
    () => [
      ...new Set(
        students
          .map((student) => String(student.class_name ?? '').trim())
          .filter(Boolean),
      ),
    ].sort((left, right) =>
      left.localeCompare(right, undefined, { numeric: true }),
    ),
    [students],
  )

  if (!token) {
    return (
      <main className="login-page">
        <section className="login-card">
          <div className="brand-mark">SM</div>
          <p className="eyebrow">School Management System</p>
          <h1>Sign in</h1>
          <p className="muted login-description">
            Sign in with your school account to access your dashboard.
          </p>
          {feedback && (
            <div className={`feedback ${feedback.type}`} role="alert">
              {feedback.text}
            </div>
          )}
          <form className="form-stack" onSubmit={handleLogin}>
            <label>
              Username
              <input name="username" autoComplete="username" required />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            <button className="primary-button full-width" disabled={loginLoading}>
              {loginLoading ? 'Signing in...' : 'Sign in'}
            </button>
          </form>
        </section>
      </main>
    )
  }

  if (userRole === 'teacher') {
    return <TeacherDashboard token={token} onLogout={handleLogout} />
  }

  if (userRole === 'student') {
    return <StudentDashboard token={token} onLogout={handleLogout} />
  }

  const directoryRows = directory[activeDirectoryRole] || []
  const activeDirectoryPagination = directoryPagination[activeDirectoryRole]
  const registrationCourses = courses.filter(
    (course) => studentClassName && getClassKey(course.class_name) === getClassKey(studentClassName),
  )
  const handleDirectoryPageChange = (nextPage) => {
    setDirectoryPages((current) => ({
      ...current,
      [activeDirectoryRole]: nextPage,
    }))
  }
  const filteredDirectoryRows = directoryRows.filter((person) => {
    const search = peopleSearch.trim().toLowerCase()
    const matchesSearch =
      !search ||
      [
        person.name,
        person.username,
        person.email,
        person.admission_number,
        person.employee_number,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(search)
    if (activeDirectoryRole !== 'students') return matchesSearch
    const matchesClass =
      studentClassFilter === 'all' || person.class_name === studentClassFilter
    const matchesCourse =
      studentCourseFilter === 'all' ||
      (person.enrolled_courses || '').includes(studentCourseFilter)
    const matchesStatus =
      studentStatusFilter === 'all' || person.status === studentStatusFilter
    return matchesSearch && matchesClass && matchesCourse && matchesStatus
  })
  const filteredFeeInvoices = feeInvoices
  const filteredPerformance = performance.filter((record) => {
    return (
      (performanceClassFilter === 'all' || record.class_name === performanceClassFilter) &&
      (performanceCourseFilter === 'all' ||
        String(record.course_id) === performanceCourseFilter) &&
      (performanceStudentFilter === 'all' ||
        String(record.student_id) === performanceStudentFilter)
    )
  })
  const schedulableCourses = courses.filter((course) => course.teacher_id)
  const schedulesForSelectedDay = schedules
    .filter((schedule) => Number(schedule.day_of_week) === selectedScheduleDay)
    .sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))
  const attendanceRecordedCount = attendanceRows.filter(
    (row) => row.attendance_status,
  ).length
  const studentAttendanceMetrics = analytics
    ? [
        ['Present', analytics.student_attendance_present_today],
        ['Absent', analytics.student_attendance_absent_today],
        ['Late', analytics.student_attendance_late_today],
        ['Excused', analytics.student_attendance_excused_today],
      ]
    : []
  const studentAttendanceTotal = studentAttendanceMetrics.reduce(
    (total, [, count]) => total + Number(count),
    0,
  )
  const staffAttendanceMetrics = analytics
    ? [
        ['Present', analytics.staff_attendance_present_today],
        ['Absent', analytics.staff_attendance_absent_today],
        ['Late', analytics.staff_attendance_late_today],
        ['On leave', analytics.staff_attendance_on_leave_today],
      ]
    : []
  const staffAttendanceTotal = staffAttendanceMetrics.reduce(
    (total, [, count]) => total + Number(count),
    0,
  )
  const feeCollectionPercent = analytics
    ? getPercentage(
        Number(analytics.fee_amount_collected),
        Number(analytics.total_fee_amount),
      )
    : 0
  const adminMetrics = dashboard?.metrics || {}
  const adminCharts = dashboard?.charts || {}
  const studentClasses = [...new Set(directory.students.map((person) => person.class_name).filter(Boolean))]
  const feeManagementClasses = feeClassOptions
  const classAssignableFeeTypes = feeTypes.filter(
    (feeType) =>
      !feeType.class_name ||
      !classFeeInvoiceClass ||
      String(feeType.class_name) === classFeeInvoiceClass,
  )
  const feeInvoiceTotals = {
    amount: Number(feeInvoiceSummary?.amount || 0),
    paid: Number(feeInvoiceSummary?.paid_amount || 0),
    pending: Number(feeInvoiceSummary?.pending_amount || 0),
  }

  return (
    <div className="admin-app">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="School admin home">
          <span className="brand-mark small">SM</span>
          <span>
            <strong>School Management</strong>
            <small>Admin console</small>
          </span>
        </a>
        <button className="secondary-button" onClick={handleLogout}>
          Sign out
        </button>
      </header>

      <main className="dashboard" id="top">
        <section className="welcome-panel">
          <div>
            <p className="eyebrow">Administration</p>
            <h1>Manage people, attendance, courses, and fee payments</h1>
            <p className="welcome-copy">
              Review student and staff profiles, record staff attendance, create
              courses, and manage student payments.
            </p>
          </div>
          <div className="summary-cards">
            <div className="summary-card">
              <span>Courses</span>
              <strong>{courses.length}</strong>
            </div>
            <div className="summary-card">
              <span>Students</span>
              <strong>{studentCount}</strong>
            </div>
            <div className="summary-card">
              <span>Students with balance</span>
              <strong>{outstandingCount}</strong>
            </div>
          </div>
        </section>

        <nav className="tabs" aria-label="Admin sections">
          <button
            className={activeTab === 'analytics' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'analytics' ? 'page' : undefined}
            onClick={() => setActiveTab('analytics')}
          >
            Analytics
          </button>
          <button
            className={activeTab === 'directory' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'directory' ? 'page' : undefined}
            onClick={() => setActiveTab('directory')}
          >
            People
          </button>
          <button
            className={activeTab === 'attendance' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'attendance' ? 'page' : undefined}
            onClick={() => setActiveTab('attendance')}
          >
            Staff attendance
          </button>
          <button
            className={activeTab === 'users' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'users' ? 'page' : undefined}
            onClick={() => setActiveTab('users')}
          >
            Users
          </button>
          <button
            className={activeTab === 'courses' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'courses' ? 'page' : undefined}
            onClick={() => setActiveTab('courses')}
          >
            Courses
          </button>
          <button
            className={activeTab === 'payment' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'payment' ? 'page' : undefined}
            onClick={() => setActiveTab('payment')}
          >
            Record payment
          </button>
          <button
            className={activeTab === 'history' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'history' ? 'page' : undefined}
            onClick={() => setActiveTab('history')}
          >
            Payment history
          </button>
          <button
            className={activeTab === 'fees' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'fees' ? 'page' : undefined}
            onClick={() => setActiveTab('fees')}
          >
            Fee management
          </button>
          <button
            className={activeTab === 'payroll' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'payroll' ? 'page' : undefined}
            onClick={() => setActiveTab('payroll')}
          >
            Salary & payroll
          </button>
          <button
            className={activeTab === 'performance' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'performance' ? 'page' : undefined}
            onClick={() => setActiveTab('performance')}
          >
            Performance
          </button>
          <button
            className={activeTab === 'events' ? 'tab active' : 'tab'}
            aria-current={activeTab === 'events' ? 'page' : undefined}
            onClick={() => setActiveTab('events')}
          >
            Events
          </button>
        </nav>

        {feedback && (
          <div className={`feedback ${feedback.type}`} role="status">
            {feedback.text}
          </div>
        )}

        {activeTab === 'analytics' && (
          analyticsLoading ? (
            <section className="panel">
              <p className="muted">Loading analytics summary...</p>
            </section>
          ) : analyticsError ? (
            <section className="panel">
              <p className="feedback error" role="alert">{analyticsError}</p>
              <button
                type="button"
                className="secondary-button"
                onClick={() => setAnalyticsRequestVersion((version) => version + 1)}
              >
                Retry analytics
              </button>
            </section>
          ) : analytics ? (
            <section className="analytics-dashboard">
              <div className="analytics-cards analytics-overview-cards">
                {[
                  ['Students', adminMetrics.total_students ?? analytics.active_students],
                  ['Teachers', adminMetrics.total_teachers ?? analytics.active_teachers],
                  ['Non-teaching staff', adminMetrics.total_non_teaching_staff ?? analytics.active_non_teaching_staff],
                  ['Courses', adminMetrics.total_courses ?? analytics.courses],
                  ['Fee collection', formatCurrency(adminMetrics.fees_collected ?? analytics.fee_amount_collected)],
                  ['Pending fees', formatCurrency(adminMetrics.pending_fees ?? analytics.fee_balance)],
                  ['Salary expenses', formatCurrency(adminMetrics.salary_expenses ?? analytics.salary_expenses)],
                  ['Staff present today', adminMetrics.staff_attendance_today?.present ?? analytics.staff_attendance_present_today ?? 0],
                ].map(([label, value]) => (
                  <article className="analytics-card" key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </article>
                ))}
              </div>

              <section className="panel fee-analytics">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">Fee collection</p>
                    <h2>Student fee balance</h2>
                  </div>
                  <strong className="analytics-percent">{feeCollectionPercent}%</strong>
                </div>
                <div className="fee-meter" aria-label={`${feeCollectionPercent}% of fees collected`}>
                  <span style={{ width: `${Math.min(feeCollectionPercent, 100)}%` }} />
                </div>
                <div className="fee-analytics-values">
                  <span>
                    Collected <strong>{formatCurrency(analytics.fee_amount_collected)}</strong>
                  </span>
                  <span>
                    Outstanding <strong>{formatCurrency(analytics.fee_balance)}</strong>
                  </span>
                  <span>
                    Expected <strong>{formatCurrency(analytics.total_fee_amount)}</strong>
                  </span>
                </div>
              </section>

              <section className="content-grid analytics-detail-grid">
                {[
                  {
                    title: 'Student attendance today',
                    metrics: studentAttendanceMetrics,
                    total: studentAttendanceTotal,
                  },
                  {
                    title: 'Staff attendance today',
                    metrics: staffAttendanceMetrics,
                    total: staffAttendanceTotal,
                  },
                ].map((group) => (
                  <article className="panel" key={group.title}>
                    <div className="panel-heading">
                      <div>
                        <p className="eyebrow">Daily summary</p>
                        <h2>{group.title}</h2>
                      </div>
                      <span className="count-pill">{group.total} records</span>
                    </div>
                    <div className="analytics-bars">
                      {group.metrics.map(([label, rawCount]) => {
                        const count = Number(rawCount)
                        return (
                          <div className="analytics-bar-row" key={label}>
                            <div>
                              <span>{label}</span>
                              <strong>{count}</strong>
                            </div>
                            <div className="analytics-bar">
                              <span
                                style={{
                                  width: `${getPercentage(count, group.total)}%`,
                                }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </article>
                ))}
              </section>

              <section className="content-grid dashboard-chart-grid">
                {[
                  {
                    title: 'Student enrollment overview',
                    eyebrow: 'By class',
                    items: (adminCharts.student_enrollment || []).map((item) => ({
                      label: item.class_name || 'Unassigned',
                      value: Number(item.student_count),
                    })),
                  },
                  {
                    title: 'Fee collection statistics',
                    eyebrow: 'Monthly collections',
                    items: (adminCharts.fee_collection || []).map((item) => ({
                      label: item.month,
                      value: Number(item.amount),
                      display: formatCurrency(item.amount),
                    })),
                  },
                  {
                    title: 'Staff attendance overview',
                    eyebrow: 'Monthly records',
                    items: (adminCharts.staff_attendance || []).map((item) => ({
                      label: `${item.month} · ${item.status.replace('_', ' ')}`,
                      value: Number(item.count),
                    })),
                  },
                  {
                    title: 'Course performance analytics',
                    eyebrow: 'Average score',
                    items: (adminCharts.course_performance || []).map((item) => ({
                      label: item.course_code,
                      value: Number(item.average_percentage),
                      display: `${item.average_percentage}%`,
                    })),
                  },
                  {
                    title: 'Class performance',
                    eyebrow: 'Average score',
                    items: (adminCharts.class_performance || []).map((item) => ({
                      label: item.class_name || 'Unassigned',
                      value: Number(item.average_percentage),
                      display: `${item.average_percentage}%`,
                    })),
                  },
                  {
                    title: 'Performance trends',
                    eyebrow: 'Monthly average',
                    items: (adminCharts.performance_trends || []).map((item) => ({
                      label: item.month,
                      value: Number(item.average_percentage),
                      display: `${item.average_percentage}%`,
                    })),
                  },
                ].map((chart) => {
                  const max = Math.max(1, ...chart.items.map((item) => item.value))
                  return (
                    <article className="panel" key={chart.title}>
                      <div className="panel-heading">
                        <div>
                          <p className="eyebrow">{chart.eyebrow}</p>
                          <h2>{chart.title}</h2>
                        </div>
                      </div>
                      {chart.items.length === 0 ? (
                        <p className="empty-state">No data available yet.</p>
                      ) : (
                        <div className="analytics-bars">
                          {chart.items.slice(0, 8).map((item) => (
                            <div className="analytics-bar-row" key={item.label}>
                              <div>
                                <span>{item.label}</span>
                                <strong>{item.display || item.value}</strong>
                              </div>
                              <div className="analytics-bar">
                                <span style={{ width: `${Math.min((item.value / max) * 100, 100)}%` }} />
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </article>
                  )
                })}
              </section>

              <section className="content-grid dashboard-lower-grid">
                <article className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Latest entries</p>
                      <h2>Recent fee payments</h2>
                    </div>
                    <button className="text-button" onClick={() => setActiveTab('history')}>View all</button>
                  </div>
                  {(dashboard?.recent_payments || []).length === 0 ? (
                    <p className="empty-state">No recent payments recorded.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead><tr><th>Student</th><th>Admission no.</th><th>Amount</th><th>Date</th></tr></thead>
                        <tbody>
                          {dashboard.recent_payments.map((payment) => (
                            <tr key={`${payment.source}-${payment.id}`}>
                              <td>{payment.student_name}</td>
                              <td>{payment.admission_number}</td>
                              <td>{formatCurrency(payment.amount)}</td>
                              <td>{new Date(payment.paid_at).toLocaleDateString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </article>
                <article className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">School calendar</p>
                      <h2>Upcoming events</h2>
                    </div>
                    <button className="text-button" onClick={() => setActiveTab('events')}>Manage</button>
                  </div>
                  {(dashboard?.upcoming_events || []).length === 0 ? (
                    <p className="empty-state">No upcoming events scheduled.</p>
                  ) : (
                    <div className="activity-list">
                      {dashboard.upcoming_events.map((item) => (
                        <div className="activity-item" key={item.id}>
                          <strong>{item.title}</strong>
                          <span>{new Date(item.starts_at).toLocaleString()}</span>
                          {item.description && <small>{item.description}</small>}
                        </div>
                      ))}
                    </div>
                  )}
                </article>
                <article className="panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">Latest changes</p>
                      <h2>Recent activities</h2>
                    </div>
                  </div>
                  {(dashboard?.recent_activities || []).length === 0 ? (
                    <p className="empty-state">No recent activity available.</p>
                  ) : (
                    <div className="activity-list">
                      {dashboard.recent_activities.map((item) => (
                        <div className="activity-item" key={item.id}>
                          <strong>{`${item.first_name} ${item.last_name}`}</strong>
                          <span>{item.roles || 'User'} · {formatDate(item.created_at)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </article>
                <article className="panel">
                  <p className="eyebrow">Shortcuts</p>
                  <h2>Quick actions</h2>
                  <div className="quick-actions">
                    {[
                      ['Add a user', 'users'],
                      ['Manage courses', 'courses'],
                      ['Assign / collect fees', 'fees'],
                      ['Generate payroll', 'payroll'],
                      ['Record attendance', 'attendance'],
                      ['Enter exam results', 'performance'],
                    ].map(([label, tab]) => (
                      <button className="secondary-button" key={tab} onClick={() => setActiveTab(tab)}>
                        {label}
                      </button>
                    ))}
                  </div>
                </article>
              </section>
            </section>
          ) : (
            <section className="panel">
              <p className="empty-state">Loading analytics...</p>
            </section>
          )
        )}{activeTab === 'users' && (
          <section className="panel user-form-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Account administration</p>
                <h2>Create a school user</h2>
              </div>
              <span className="step-number">01</span>
            </div>
            <form className="form-stack" onSubmit={handleCreateUser}>
              <div className="field-row">
                <label>
                  First name
                  <input name="first_name" maxLength="100" required />
                </label>
                <label>
                  Last name
                  <input name="last_name" maxLength="100" required />
                </label>
              </div>
              <div className="field-row">
                <label>
                  Username
                  <input
                    name="username"
                    minLength="3"
                    maxLength="80"
                    autoComplete="off"
                    required
                  />
                </label>
                <label>
                  Temporary password
                  <input
                    name="password"
                    type="password"
                    minLength="8"
                    maxLength="128"
                    autoComplete="new-password"
                    required
                  />
                </label>
              </div>
              <div className="field-row">
                <label>
                  Email
                  <input name="email" type="email" maxLength="254" required />
                </label>
                <label>
                  Phone
                  <input name="phone" type="tel" maxLength="30" required />
                </label>
              </div>
              <label>
                Profile photo <span className="optional">(JPG, PNG, WEBP; max 5 MB)</span>
                <input name="profile_photo" type="file" accept=".jpg,.jpeg,.png,.webp" />
              </label>
              <label>
                Role
                <select
                  name="role"
                  value={newUserRole}
                  onChange={(event) => setNewUserRole(event.target.value)}
                >
                  <option value="student">Student</option>
                  <option value="teacher">Teacher</option>
                  <option value="non_teaching_staff">Non-teaching staff</option>
                </select>
              </label>

              {newUserRole === 'student' && (
                <div className="role-fields">
                  <h3>Student details</h3>
                  <div className="field-row">
                    <label>
                      Admission number <span className="optional">(generated automatically)</span>
                      <input
                        name="admission_number"
                        value={getNextAdmissionNumber(students)}
                        maxLength="40"
                        readOnly
                        required
                      />
                    </label>
                    <label>
                      Date of birth <span className="optional">(minimum age: 5)</span>
                      <input
                        name="date_of_birth"
                        type="date"
                        max={getDateYearsAgo(5)}
                        required
                      />
                    </label>
                  </div>
                  <div className="field-row">
                    <fieldset className="choice-group">
                      <legend>Gender</legend>
                      <div className="choice-options radio-options">
                        <label className="choice-option">
                          <input type="radio" name="gender" value="female" required />
                          <span>Female</span>
                        </label>
                        <label className="choice-option">
                          <input type="radio" name="gender" value="male" />
                          <span>Male</span>
                        </label>
                        <label className="choice-option">
                          <input type="radio" name="gender" value="other" />
                          <span>Other</span>
                        </label>
                      </div>
                    </fieldset>
                    <label>
                      Admission date
                      <input
                        name="admission_date"
                        type="date"
                        max={getLocalDate()}
                        required
                      />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Class
                      <input
                        name="class_name"
                        maxLength="80"
                        placeholder="e.g. 10-A"
                        value={studentClassName}
                        onChange={(event) => setStudentClassName(event.target.value)}
                        required
                      />
                    </label>
                    <label>
                      Total fee
                      <input
                        name="fee_amount"
                        type="number"
                        min="0"
                        step="0.01"
                        required
                      />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Academic year
                      <select name="academic_year_id" defaultValue="" required>
                        <option value="" disabled>
                          Select an academic year
                        </option>
                        {academicYears.map((year) => (
                          <option key={year.id} value={year.id}>
                            {year.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <fieldset className="choice-group">
                      <legend>Enrolled courses <span className="optional">(select one or more)</span></legend>
                      <div className="choice-options course-options">
                        {registrationCourses.map((course) => (
                          <label className="choice-option" key={course.id}>
                            <input
                              type="checkbox"
                              name="course_ids"
                              value={course.id}
                            />
                            <span>{course.course_code} - {course.name}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  </div>
                  <label>
                    Address
                    <textarea name="address" rows="3" maxLength="500" required />
                  </label>
                  <div className="field-row">
                    <label>
                      Parent / guardian name
                      <input name="parent_guardian_name" maxLength="160" />
                    </label>
                    <label>
                      Parent contact
                      <input name="parent_contact" type="tel" maxLength="30" />
                    </label>
                  </div>
                  {courses.length === 0 && (
                    <p className="inline-hint">Create a course before adding a student.</p>
                  )}
                  {!studentClassName && courses.length > 0 && (
                    <p className="inline-hint">Enter the student's class to see matching courses.</p>
                  )}
                  {studentClassName && registrationCourses.length === 0 && (
                    <p className="inline-hint">No courses are assigned to class {studentClassName}.</p>
                  )}
                  {academicYears.length === 0 && (
                    <p className="inline-hint">Add an academic year before adding a student.</p>
                  )}
                </div>
              )}

              {newUserRole === 'teacher' && (
                <div className="role-fields">
                  <h3>Teacher details</h3>
                  <div className="field-row">
                    <label>
                      Joining date
                      <input name="joining_date" type="date" required />
                    </label>
                    <label>
                      Experience (years)
                      <input
                        name="experience_years"
                        type="number"
                        min="0"
                        step="0.1"
                        defaultValue="0"
                      />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Department
                      <input name="department" maxLength="120" />
                    </label>
                    <label>
                      Base salary
                      <input
                        name="salary"
                        type="number"
                        min="0"
                        step="0.01"
                        required
                      />
                    </label>
                  </div>
                  <label>
                    Address
                    <textarea name="staff_address" rows="2" maxLength="500" />
                  </label>
                  <label>
                    Education
                    <textarea name="education" rows="3" maxLength="500" required />
                  </label>
                  <label>
                    Courses taught
                    <select
                      className="multi-select"
                      name="course_ids"
                      multiple
                      required
                      size={Math.min(Math.max(courses.length, 2), 5)}
                    >
                      {courses.map((course) => (
                        <option key={course.id} value={course.id}>
                          {course.course_code} - {course.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {courses.length === 0 && (
                    <p className="inline-hint">Create a course before adding a teacher.</p>
                  )}
                </div>
              )}

              {newUserRole === 'non_teaching_staff' && (
                <div className="role-fields">
                  <h3>Non-teaching staff details</h3>
                  <div className="field-row">
                    <label>
                      Work / position
                      <input name="work" maxLength="120" required />
                    </label>
                    <label>
                      Shift
                      <input
                        name="shift"
                        maxLength="80"
                        placeholder="e.g. Morning"
                        required
                      />
                    </label>
                  </div>
                  <div className="field-row">
                    <label>
                      Joining date
                      <input name="staff_joining_date" type="date" />
                    </label>
                    <label>
                      Department
                      <input name="department" maxLength="120" />
                    </label>
                  </div>
                  <label>
                    Address
                    <textarea name="staff_address" rows="2" maxLength="500" />
                  </label>
                  <label>
                    Base salary
                    <input
                      name="salary"
                      type="number"
                      min="0"
                      step="0.01"
                      required
                    />
                  </label>
                </div>
              )}

              <button className="primary-button" disabled={userLoading}>
                {userLoading ? 'Creating user...' : 'Create user'}
              </button>
            </form>
          </section>
        )}

        {activeTab === 'directory' && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">School directory</p>
                <h2>
                  {activeDirectoryRole === 'students'
                    ? 'Students'
                    : activeDirectoryRole === 'teachers'
                      ? 'Teachers'
                      : 'Non-teaching staff'}
                </h2>
              </div>
              <span className="count-pill">{directoryRows.length} people</span>
            </div>
            <div className="directory-tabs" role="group" aria-label="People category">
              {[
                ['students', 'Students'],
                ['teachers', 'Teachers'],
                ['non_teaching_staff', 'Non-teaching staff'],
              ].map(([role, label]) => (
                <button
                  key={role}
                  className={
                    activeDirectoryRole === role
                      ? 'directory-tab active'
                      : 'directory-tab'
                  }
                  onClick={() => {
                    setActiveDirectoryRole(role)
                    setPeopleSearch('')
                    setDirectoryPages((current) => ({ ...current, [role]: 1 }))
                  }}
                  aria-pressed={activeDirectoryRole === role}
                >
                  {label}
                  <span>{directory[role].length}</span>
                </button>
              ))}
            </div>
            <div className="filter-row">
              <label>
                Search
                <input value={peopleSearch} onChange={(event) => setPeopleSearch(event.target.value)} placeholder="Name, ID, email, phone" />
              </label>
              {activeDirectoryRole === 'students' && (
                <>
                  <label>
                    Class
                    <select value={studentClassFilter} onChange={(event) => setStudentClassFilter(event.target.value)}>
                      <option value="all">All classes</option>
                      {studentClasses.map((className) => <option key={className} value={className}>{className}</option>)}
                    </select>
                  </label>
                  <label>
                    Course
                    <select value={studentCourseFilter} onChange={(event) => setStudentCourseFilter(event.target.value)}>
                      <option value="all">All courses</option>
                      {courses.map((course) => <option key={course.id} value={course.course_code}>{course.course_code}</option>)}
                    </select>
                  </label>
                  <label>
                    Status
                    <select value={studentStatusFilter} onChange={(event) => setStudentStatusFilter(event.target.value)}>
                      <option value="all">All statuses</option>
                      <option value="active">Active</option>
                      <option value="inactive">Inactive</option>
                      <option value="graduated">Graduated</option>
                      <option value="withdrawn">Withdrawn</option>
                    </select>
                  </label>
                </>
              )}
            </div>
            {directoryLoading ? (
              <p className="empty-state">Loading directory records...</p>
            ) : directoryRows.length === 0 ? (
              <p className="empty-state">No {activeDirectoryRole.replace('_', ' ')} found.</p>
            ) : filteredDirectoryRows.length === 0 ? (
              <p className="empty-state">No people match these filters.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  {activeDirectoryRole === 'students' ? (
                    <>
                      <thead>
                        <tr>
                          <th>Student</th>
                          <th>Admission no.</th>
                          <th>Contact</th>
                          <th>Class / courses</th>
                          <th>Admission date</th>
                          <th>Address</th>
                          <th>Fees</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredDirectoryRows.map((student) => {
                          const payment = students.find((item) => item.id === student.id)
                          return (
                            <tr key={student.id}>
                              <td>
                                <strong>{student.name}</strong>
                                <small>{student.username}</small>
                              </td>
                              <td>{student.admission_number}</td>
                              <td>
                                <strong>{student.email}</strong>
                                <small>{student.phone || '-'}</small>
                              </td>
                              <td>
                                <strong>{student.class_name}</strong>
                                <small>{student.enrolled_courses || 'No courses'}</small>
                              </td>
                              <td>{formatDate(student.admission_date)}</td>
                              <td className="address-cell">{student.address || '-'}</td>
                              <td>
                                <strong>{formatCurrency(student.fee_amount)}</strong>
                                <small>
                                  Balance {formatCurrency(payment?.balance ?? student.fee_amount)}
                                </small>
                              </td>
                              <td>
                                <span className={`status-pill ${student.status}`}>
                                  {student.status}
                                </span>
                              </td>
                              <td><div className="table-actions">
                                <button className="text-button" onClick={() => setEditingStudent(student)}>Edit</button>
                                <button className="text-button" onClick={() => handleOpenStudentProfile(student.id)}>Profile</button>
                                <button className="text-button danger-text" disabled={!student.user_id} onClick={() => handleDeleteUser({ id: student.user_id, name: student.name })}>Delete</button>
                              </div></td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </>
                  ) : (
                    <>
                      <thead>
                        <tr>
                          <th>Staff member</th>
                          <th>Employee no.</th>
                          <th>Contact</th>
                          <th>{activeDirectoryRole === 'teachers' ? 'Courses' : 'Work / shift'}</th>
                          <th>Joining date</th>
                          {activeDirectoryRole === 'teachers' && <th>Education</th>}
                          <th>Base salary</th>
                          <th>Status</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredDirectoryRows.map((staff) => (
                          <tr key={staff.id}>
                            <td>
                              <strong>{staff.name}</strong>
                              <small>{staff.username} · {staff.designation}</small>
                            </td>
                            <td>{staff.employee_number}</td>
                            <td>
                              <strong>{staff.email}</strong>
                              <small>{staff.phone || '-'}</small>
                            </td>
                            <td>
                              <strong>
                                {activeDirectoryRole === 'teachers'
                                  ? staff.courses_taught || 'No courses'
                                  : staff.designation}
                              </strong>
                              {activeDirectoryRole === 'non_teaching_staff' && (
                                <small>{staff.shift || '-'}</small>
                              )}
                            </td>
                            <td>{formatDate(staff.hire_date)}</td>
                            {activeDirectoryRole === 'teachers' && (
                              <td>{staff.education || '-'}</td>
                            )}
                            <td>{formatCurrency(staff.base_salary)}</td>
                            <td>
                              <span className={`status-pill ${staff.status}`}>
                                {staff.status}
                              </span>
                            </td>
                            <td><div className="table-actions">
                              <button className="text-button" onClick={() => setEditingStaff(staff)}>Edit</button>
                              <button className="text-button danger-text" disabled={!staff.user_id} onClick={() => handleDeleteUser({ id: staff.user_id, name: staff.name })}>Delete</button>
                            </div></td>
                          </tr>
                        ))}
                      </tbody>
                    </>
                  )}
                </table>
              </div>
            )}
            <PaginationControls
              pagination={activeDirectoryPagination}
              onPageChange={handleDirectoryPageChange}
              disabled={directoryLoading}
            />
          </section>
        )}

        {activeTab === 'attendance' && (
          <>
          <section className="content-grid attendance-grid">
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Staff timekeeping</p>
                  <h2>Record attendance</h2>
                </div>
                <span className="step-number">01</span>
              </div>
              <form className="form-stack" onSubmit={handleRecordAttendance}>
                <label>
                  Attendance date
                  <input
                    name="attendance_date"
                    type="date"
                    value={attendanceDate}
                    onChange={(event) => {
                      setAttendanceLoading(true)
                      setAttendancePage(1); setAttendanceDate(event.target.value)
                    }}
                    required
                  />
                </label>
                <label>
                  Staff member
                  <select name="staff_id" defaultValue="" required>
                    <option value="" disabled>
                      Select a staff member
                    </option>
                    {attendanceRows.map((staff) => (
                      <option key={staff.staff_id} value={staff.staff_id}>
                        {staff.name} | {staff.employee_number} |{' '}
                        {staff.staff_type === 'teacher' ? 'Teacher' : 'Non-teaching'}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Attendance
                  <select name="status" defaultValue="present" required>
                    {ATTENDANCE_STATUSES.map((status) => (
                      <option key={status.value} value={status.value}>
                        {status.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="field-row">
                  <label>
                    Check-in <span className="optional">(optional)</span>
                    <input name="check_in" type="time" />
                  </label>
                  <label>
                    Check-out <span className="optional">(optional)</span>
                    <input name="check_out" type="time" />
                  </label>
                </div>
                <label>
                  Notes <span className="optional">(optional)</span>
                  <textarea name="notes" rows="3" maxLength="500" />
                </label>
                <button
                  className="primary-button"
                  disabled={attendanceSubmitting || attendanceRows.length === 0}
                >
                  {attendanceSubmitting ? 'Saving attendance...' : 'Save attendance'}
                </button>
                {attendanceRows.length === 0 && !attendanceLoading && (
                  <p className="inline-hint">
                    Add an active teacher or non-teaching staff account first.
                  </p>
                )}
              </form>
            </div>
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Daily register</p>
                  <h2>Staff attendance</h2>
                  <p className="muted">{formatDate(attendanceDate)}</p>
                </div>
                <span className="count-pill">
                  {attendanceRecordedCount}/{attendanceRows.length} on this page recorded
                </span>
              </div>
              <label className="attendance-search">
                Search staff, employee no., designation, department or course
                <input
                  type="search"
                  value={attendanceSearch}
                  onChange={(event) => setAttendanceSearch(event.target.value)}
                  placeholder="Type a staff name or course..."
                />
              </label>
              {attendanceLoading ? (
                <p className="empty-state">Loading attendance...</p>
              ) : attendanceRows.length === 0 ? (
                <p className="empty-state">No active staff accounts found.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Staff member</th>
                        <th>Role</th>
                        <th>Status</th>
                        <th>Check-in</th>
                        <th>Check-out</th>
                        <th>Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {attendanceRows.map((staff) => (
                        <tr key={staff.staff_id}>
                          <td>
                            <strong>{staff.name}</strong>
                            <small>{staff.employee_number}</small>
                          </td>
                          <td>{staff.designation}</td>
                          <td>
                            {staff.attendance_status ? (
                              <span
                                className={`attendance-pill ${staff.attendance_status}`}
                              >
                                {ATTENDANCE_STATUSES.find(
                                  (item) => item.value === staff.attendance_status,
                                )?.label || staff.attendance_status}
                              </span>
                            ) : (
                              <span className="status-pill not-recorded">Not recorded</span>
                            )}
                          </td>
                          <td>{staff.check_in || '-'}</td>
                          <td>{staff.check_out || '-'}</td>
                          <td className="address-cell">{staff.notes || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {attendancePagination && (
                <PaginationControls
                  pagination={attendancePagination}
                  disabled={attendanceLoading}
                  onPageChange={setAttendancePage}
                />
              )}
            </div>
          </section>
          <section className="panel attendance-report-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">Monthly report</p><h2>Staff attendance history</h2></div>
              <div className="report-filters">
                <label>Month<input type="month" value={attendanceDate.slice(0, 7)} onChange={(event) => { setAttendanceReportLoading(true); setAttendanceReportPage(1); setAttendanceDate(`${event.target.value}-01`) }} /></label>
                <label>Staff role<select value={attendanceRoleFilter} onChange={(event) => { setAttendanceReportLoading(true); setAttendancePage(1); setAttendanceReportPage(1); setAttendanceRoleFilter(event.target.value) }}><option value="all">All staff</option><option value="teacher">Teachers</option><option value="non_teaching">Non-teaching staff</option></select></label>
                <label>Search staff or course<input type="search" value={attendanceReportSearch} onChange={(event) => setAttendanceReportSearch(event.target.value)} placeholder="Name, employee no., course..." /></label>
              </div>
            </div>
            {attendanceReportLoading ? <p className="empty-state">Loading monthly report...</p> : attendanceReport && (
              <>
                <div className="analytics-cards attendance-summary">
                  {Object.entries(attendanceReport.summary || {}).map(([status, count]) => <article className="analytics-card" key={status}><span>{status.replace('_', ' ')}</span><strong>{count}</strong></article>)}
                </div>
                <div className="table-wrap">
                  <table><thead><tr><th>Date</th><th>Staff member</th><th>Role</th><th>Status</th><th>Check-in</th><th>Check-out</th><th>Notes</th></tr></thead><tbody>
                    {(attendanceReport.records || []).map((record, index) => <tr key={`${record.staff_id}-${record.attendance_date}-${index}`}><td>{formatDate(record.attendance_date)}</td><td>{record.name}<small>{record.employee_number}</small></td><td>{record.staff_type === 'teacher' ? 'Teacher' : 'Non-teaching staff'}</td><td><span className={`attendance-pill ${record.status}`}>{record.status.replace('_', ' ')}</span></td><td>{record.check_in || '-'}</td><td>{record.check_out || '-'}</td><td>{record.notes || '-'}</td></tr>)}
                    {(attendanceReport.records || []).length === 0 && <tr><td colSpan="7">No attendance records for this month.</td></tr>}
                  </tbody></table>
                </div>
                {attendanceReport.pagination && (
                  <PaginationControls
                    pagination={attendanceReport.pagination}
                    disabled={attendanceReportLoading}
                    onPageChange={setAttendanceReportPage}
                  />
                )}
              </>
            )}
          </section>
          </>
        )}

        {activeTab === 'courses' && (
          <>
          <section className="content-grid">
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Course setup</p>
                  <h2>Create a course</h2>
                </div>
                <span className="step-number">01</span>
              </div>
              <form className="form-stack" onSubmit={handleCreateCourse}>
                <div className="field-row">
                  <label>
                    Course code
                    <input name="course_code" placeholder="e.g. BIO-101" maxLength="40" required />
                  </label>
                  <label>
                    Course name
                    <input name="name" placeholder="e.g. Biology" maxLength="150" required />
                  </label>
                </div>
                <div className="field-row">
                  <label>
                    Class / grade
                    <input name="class_name" maxLength="80" placeholder="e.g. 10-A" />
                  </label>
                  <label>
                    Duration (months)
                    <input name="duration_months" type="number" min="1" max="120" />
                  </label>
                </div>
                <div className="field-row">
                  <label>
                    Academic year
                    <select name="course_academic_year_id" defaultValue="">
                      <option value="">Not specified</option>
                      {academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}
                    </select>
                  </label>
                  <label>
                    Assigned teacher
                    <select name="course_teacher_id" defaultValue="">
                      <option value="">Unassigned</option>
                      {directory.teachers.map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.name}</option>)}
                    </select>
                  </label>
                </div>
                <label>
                  Description <span className="optional">(optional)</span>
                  <textarea
                    name="description"
                    rows="4"
                    maxLength="5000"
                    placeholder="Add a short course description"
                  />
                </label>
                <button className="primary-button" disabled={courseLoading}>
                  {courseLoading ? 'Creating...' : 'Create course'}
                </button>
              </form>
            </div>

            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Course catalog</p>
                  <h2>Course catalog</h2>
                </div>
                <span className="count-pill">{courseCatalogPagination?.total_records ?? courseCatalog.length}</span>
              </div>
              <div className="filter-row">
                <label>
                  Search
                  <input
                    type="search"
                    value={courseCatalogSearch}
                    onChange={(event) => setCourseCatalogSearch(event.target.value)}
                    placeholder="Course name, code, or class"
                  />
                </label>
                <label>
                  Class
                  <select
                    value={courseClassFilter}
                    onChange={(event) => {
                      setCourseClassFilter(event.target.value)
                      setCourseCatalogPage(1)
                    }}
                  >
                    <option value="all">All classes</option>
                    {[...new Set(courses.map((course) => course.class_name).filter(Boolean))].sort().map((className) => (
                      <option key={className} value={className}>{className}</option>
                    ))}
                  </select>
                </label>
              </div>
              {courseCatalog.length === 0 ? (
                <p className="empty-state">No courses have been created yet.</p>
              ) : (
                <div className="course-list">
                  {courseCatalog.map((course) => (
                    <article className="course-row" key={course.id}>
                      <span className="course-code">{course.course_code}</span>
                      <div>
                        <strong>{course.name}</strong>
                        <p>{course.description || 'No description'} · {course.class_name || 'No class'} · {directory.teachers.find((teacher) => teacher.id === course.teacher_id)?.name || 'Unassigned'}</p>
                      </div>
                      <span className="row-id">#{course.id}</span>
                      <div className="table-actions">
                        <button className="text-button" onClick={() => handleLoadEnrollments(course)}>View details</button>
                        <button className="text-button" onClick={() => setSelectedCourse(course)}>Edit</button>
                        <button className="text-button" onClick={() => handleLoadEnrollments(course)}>Enrollments</button>
                        <button className="text-button danger-text" onClick={() => handleDeleteCourse(course)}>Delete</button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {courseCatalogPagination && (
                <PaginationControls
                  pagination={courseCatalogPagination}
                  onPageChange={setCourseCatalogPage}
                />
              )}
            </div>
          </section>
          {selectedCourse && (
            <section className="content-grid">
              <div className="panel">
                <div className="panel-heading">
                  <div><p className="eyebrow">Course management</p><h2>Edit {selectedCourse.course_code}</h2></div>
                  <button className="text-button" onClick={() => setSelectedCourse(null)}>Close</button>
                </div>
                <form className="form-stack" onSubmit={handleSaveCourse}>
                  <div className="field-row">
                    <label>Course code<input name="course_code" defaultValue={selectedCourse.course_code} required /></label>
                    <label>Course name<input name="name" defaultValue={selectedCourse.name} required /></label>
                  </div>
                  <label>Description<textarea name="description" rows="3" defaultValue={selectedCourse.description || ''} /></label>
                  <div className="field-row">
                    <label>Class / grade<input name="class_name" defaultValue={selectedCourse.class_name || ''} /></label>
                    <label>Duration (months)<input name="duration_months" type="number" min="1" max="120" defaultValue={selectedCourse.duration_months || ''} /></label>
                  </div>
                  <div className="field-row">
                    <label>Academic year<select name="academic_year_id" defaultValue={selectedCourse.academic_year_id || ''}><option value="">Not specified</option>{academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}</select></label>
                    <label>Assigned teacher<select name="teacher_id" defaultValue={selectedCourse.teacher_id || ''}><option value="">Unassigned</option>{directory.teachers.map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.name}</option>)}</select></label>
                  </div>
                  <button className="primary-button">Save course</button>
                </form>
              </div>
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Course enrollment</p><h2>{selectedCourse.name}</h2></div><span className="count-pill">{courseEnrollments.length} students</span></div>
                <form className="form-stack compact-form" onSubmit={handleEnrollStudent}>
                  <div className="field-row">
                    <label>
                      Find student
                      <input
                        type="search"
                        value={enrollmentStudentSearch}
                        onChange={(event) => setEnrollmentStudentSearch(event.target.value)}
                        placeholder="Name or admission number"
                      />
                    </label>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={handleSearchEnrollmentStudents}
                      disabled={enrollmentStudentSearchLoading}
                    >
                      {enrollmentStudentSearchLoading ? 'Searching...' : 'Search'}
                    </button>
                  </div>
                  <div className="field-row">
                    <label>
                      Student
                      <select name="student_id" defaultValue="" required>
                        <option value="" disabled>
                          {enrollmentStudents.length ? 'Select student' : 'No students found'}
                        </option>
                        {enrollmentStudents.map((student) => (
                          <option key={student.id} value={student.id}>
                            {student.name} · {student.admission_number}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>Academic year<select name="academic_year_id" defaultValue={academicYears.find((year) => year.is_current)?.id || academicYears[0]?.id || ''} required>{academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}</select></label>
                  </div>
                  <button className="primary-button">Enroll student</button>
                </form>
                <div className="activity-list">
                  {courseEnrollments.map((enrollment) => (
                    <div className="activity-item" key={`${enrollment.student_id}-${enrollment.academic_year_id}`}>
                      <strong>{enrollment.student_name}</strong>
                      <span>{enrollment.admission_number} · {enrollment.class_name} · {enrollment.enrollment_status}</span>
                      {enrollment.enrollment_status === 'enrolled' && <button className="text-button danger-text" onClick={() => handleWithdrawStudent(enrollment)}>Withdraw</button>}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}
          <section className="content-grid schedule-grid">
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Weekly timetable</p>
                  <h2>Schedule a class</h2>
                </div>
              </div>
              <form className="form-stack" onSubmit={handleCreateSchedule}>
                <label>
                  Assigned course
                  <select name="course_id" defaultValue="" required>
                    <option value="" disabled>
                      Select a course
                    </option>
                    {schedulableCourses.map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.course_code} - {course.name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="field-row">
                  <label>
                    Day
                    <select name="day_of_week" defaultValue="0" required>
                      {WEEKDAYS.map((day, index) => (
                        <option key={day} value={index}>
                          {day}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Class
                    <input name="class_name" maxLength="80" placeholder="e.g. 10-A" />
                  </label>
                </div>
                <div className="field-row">
                  <label>
                    Start time
                    <input name="start_time" type="time" required />
                  </label>
                  <label>
                    End time
                    <input name="end_time" type="time" required />
                  </label>
                </div>
                <label>
                  Room <span className="optional">(optional)</span>
                  <input name="room" maxLength="80" placeholder="e.g. Room 12" />
                </label>
                <button
                  className="primary-button"
                  disabled={scheduleLoading || schedulableCourses.length === 0}
                >
                  {scheduleLoading ? 'Saving schedule...' : 'Add to timetable'}
                </button>
                {schedulableCourses.length === 0 && (
                  <p className="inline-hint">
                    Assign a teacher to a course before scheduling a class.
                  </p>
                )}
              </form>
            </div>
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Weekly timetable</p>
                  <h2>Scheduled classes</h2>
                </div>
                <span className="count-pill">{schedulesForSelectedDay.length} classes</span>
              </div>
              <div className="schedule-day-tabs" role="tablist" aria-label="Schedule day">
                {WEEKDAYS.map((day, index) => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={selectedScheduleDay === index}
                    className={selectedScheduleDay === index ? 'schedule-day-tab active' : 'schedule-day-tab'}
                    key={day}
                    onClick={() => {
                      setSelectedScheduleDay(index)
                      setSchedulePage(1)
                    }}
                  >
                    {day}
                    <span>{scheduleDayCounts[index] || 0}</span>
                  </button>
                ))}
              </div>
              {schedulesForSelectedDay.length === 0 ? (
                <p className="empty-state">No class schedules have been added for {WEEKDAYS[selectedScheduleDay]}.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Day / time</th>
                        <th>Course</th>
                        <th>Teacher</th>
                        <th>Class / room</th>
                      </tr>
                    </thead>
                    <tbody>
                      {schedulesForSelectedDay.map((schedule) => (
                        <tr key={schedule.id}>
                          <td>
                            <strong>{WEEKDAYS[schedule.day_of_week]}</strong>
                            <small>
                              {schedule.start_time} - {schedule.end_time}
                            </small>
                          </td>
                          <td>
                            <strong>{schedule.course_code}</strong>
                            <small>{schedule.course_name}</small>
                          </td>
                          <td>{schedule.teacher_name || 'Unassigned'}</td>
                          <td>
                            <strong>{schedule.class_name || '-'}</strong>
                            <small>{schedule.room || '-'}</small>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {schedulePagination && schedulePagination.total_records > 0 && (
                <PaginationControls
                  pagination={schedulePagination}
                  onPageChange={setSchedulePage}
                />
              )}
            </div>
          </section>
          </>
        )}

        {activeTab === 'fees' && (
          <section className="analytics-dashboard">
            <div className="analytics-cards">
              <article className="analytics-card"><span>Invoice total</span><strong>{formatCurrency(feeInvoiceTotals.amount)}</strong></article>
              <article className="analytics-card"><span>Collected</span><strong>{formatCurrency(feeInvoiceTotals.paid)}</strong></article>
              <article className="analytics-card"><span>Pending</span><strong>{formatCurrency(feeInvoiceTotals.pending)}</strong></article>
              <article className="analytics-card"><span>Invoices</span><strong>{feeInvoicePagination?.total_records ?? feeInvoices.length}</strong></article>
            </div>
            {feeReferencesError && (
              <p className="inline-hint" role="alert">
                {feeReferencesError}{' '}
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setFeeReferencesRefreshVersion((version) => version + 1)}
                >
                  Retry
                </button>
              </p>
            )}
            {feeReferencesLoading && (
              <p className="muted">Loading student and academic-year options...</p>
            )}
            <section className="content-grid">
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Fee setup</p><h2>Add fee structure</h2></div></div>
                <form className="form-stack" onSubmit={handleCreateFeeType}>
                  <label>Fee name<input name="name" maxLength="100" required placeholder="Tuition fee" /></label>
                  <label>Description<input name="description" maxLength="255" /></label>
                  <div className="field-row">
                    <label>Amount<input name="amount" type="number" min="0" step="0.01" required /></label>
                    <label>Class / grade<input name="class_name" maxLength="80" /></label>
                  </div>
                  <label>Academic year<select name="academic_year_id" defaultValue=""><option value="">All years</option>{academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}</select></label>
                  <button className="primary-button" disabled={feeLoading}>{feeLoading ? 'Saving...' : 'Create fee structure'}</button>
                </form>
                <div className="section-divider"><p className="eyebrow">Available structures</p></div>
                {feeTypesError && (
                  <p className="inline-hint" role="alert">
                    {feeTypesError}{' '}
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setFeeTypesRefreshVersion((version) => version + 1)}
                    >
                      Retry
                    </button>
                  </p>
                )}
                {feeTypes.length === 0 ? (
                  <p className="empty-state">
                    {feeTypesLoading
                      ? 'Loading fee structures...'
                      : feeTypesError
                        ? 'Fee structures could not be loaded.'
                        : 'No fee structures created.'}
                  </p>
                ) : (
                  <div className="activity-list">
                    {feeTypes.map((feeType) => <div className="activity-item" key={feeType.id}><strong>{feeType.name} · {formatCurrency(feeType.amount)}</strong><span>{feeType.class_name || 'All classes'} · {feeType.academic_year || 'All years'}</span></div>)}
                  </div>
                )}
              </div>
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Student billing</p><h2>Manage an extra fee for a student</h2></div></div>
                <p className="muted panel-intro">
                  Select a student and shared fee such as Tuition or Exam. Assign an invoice, or
                  record payment against an invoice already assigned to that student.
                </p>
                <div className="filter-row">
                  <button
                    type="button"
                    className={feeStudentBillingMode === 'payment' ? 'primary-button' : 'secondary-button'}
                    aria-pressed={feeStudentBillingMode === 'payment'}
                    onClick={() => setFeeStudentBillingMode('payment')}
                  >
                    Record payment
                  </button>
                  <button
                    type="button"
                    className={feeStudentBillingMode === 'assign' ? 'primary-button' : 'secondary-button'}
                    aria-pressed={feeStudentBillingMode === 'assign'}
                    onClick={() => setFeeStudentBillingMode('assign')}
                  >
                    Assign invoice only
                  </button>
                </div>
                <form
                  className="form-stack"
                  onSubmit={feeStudentBillingMode === 'payment' ? handleRecordExtraFeePayment : handleAssignFee}
                >
                  <label>
                    Find student
                    <input
                      type="search"
                      value={feeStudentSearch}
                      onChange={(event) => {
                        setFeeStudentSearch(event.target.value)
                        setFeeStudentPage(1)
                      }}
                      maxLength="120"
                      placeholder="Name, surname, or admission number"
                    />
                  </label>
                  <label>
                    Student
                    <select
                      name="student_id"
                      value={feeAssignmentStudent ? String(feeAssignmentStudent.id) : ''}
                      onChange={(event) => {
                        const selected = feeStudents.find(
                          (student) => String(student.id) === event.target.value,
                        )
                        setFeeAssignmentStudent(selected || null)
                      }}
                      required
                    >
                      <option value="" disabled>
                        {feeStudentLoading
                          ? 'Loading students...'
                          : feeStudentError
                            ? 'Student search failed'
                            : feeStudents.length
                              ? 'Select student'
                              : 'No students found'}
                      </option>
                      {feeAssignmentStudent &&
                        !feeStudents.some(
                          (student) => String(student.id) === String(feeAssignmentStudent.id),
                        ) && (
                          <option value={feeAssignmentStudent.id}>
                            {feeAssignmentStudent.name} · {feeAssignmentStudent.admission_number}
                          </option>
                        )}
                      {feeStudents.map((student) => (
                        <option key={student.id} value={student.id}>
                          {student.name} · {student.admission_number}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>Shared fee structure<select name="fee_type_id" value={feeAssignmentFeeType} onChange={(event) => setFeeAssignmentFeeType(event.target.value)} required><option value="" disabled>Select fee</option>{feeTypes.map((feeType) => <option key={feeType.id} value={feeType.id}>{feeType.name} · {formatCurrency(feeType.amount)}</option>)}</select></label>
                  <label>Academic year<select name="academic_year_id" defaultValue={academicYears.find((year) => year.is_current)?.id || ''} required>{academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}</select></label>
                  {feeStudentBillingMode === 'payment' ? (
                    <>
                      <p className="muted">
                        This records the amount received. If no invoice exists for this student,
                        fee, and year, one will be created using the shared fee amount.
                      </p>
                      <label>
                        Amount received
                        <input name="amount" type="number" min="0.01" step="0.01" required />
                      </label>
                      <label>
                        Due date for any remaining balance
                        <input name="invoice_due_date" type="date" />
                      </label>
                      <label>
                        Payment method
                        <select
                          name="payment_method"
                          value={invoicePaymentMethod}
                          onChange={(event) => setInvoicePaymentMethod(event.target.value)}
                          required
                        >
                          {PAYMENT_METHODS.map((method) => (
                            <option key={method} value={method}>{method.replace('_', ' ')}</option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Transaction reference <span className="optional">(optional)</span>
                        <input name="transaction_reference" maxLength="120" />
                      </label>
                      <label>
                        Notes <span className="optional">(optional)</span>
                        <input name="notes" maxLength="500" />
                      </label>
                      <button
                        className="primary-button"
                        disabled={feeLoading || feeStudentLoading || feeReferencesLoading || feeTypesLoading || !feeTypes.length}
                      >
                        {feeLoading ? 'Recording payment...' : 'Record payment & generate receipt'}
                      </button>
                    </>
                  ) : (
                    <>
                      <div className="field-row">
                        <label>Override amount <span className="optional">(optional)</span><input name="amount" type="number" min="0.01" step="0.01" /></label>
                        <label>Due date<input name="due_date" type="date" required /></label>
                      </div>
                      <button
                        className="primary-button"
                        disabled={feeLoading || feeStudentLoading || feeReferencesLoading || feeTypesLoading || !feeTypes.length}
                      >
                        {feeLoading ? 'Assigning...' : 'Assign fee'}
                      </button>
                    </>
                  )}
                </form>
                {feeStudentError && (
                  <p className="inline-hint" role="alert">
                    {feeStudentError}{' '}
                    <button
                      type="button"
                      className="text-button"
                      onClick={() => setFeeStudentRefreshVersion((version) => version + 1)}
                    >
                      Retry
                    </button>
                  </p>
                )}
                {feeStudentPagination && (
                  <div className="pagination-controls">
                    <span className="muted">Student options page {feeStudentPagination.page}</span>
                    <div className="pagination-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => setFeeStudentPage((page) => page - 1)}
                        disabled={feeStudentLoading || !feeStudentPagination.has_previous}
                      >
                        Previous
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => setFeeStudentPage((page) => page + 1)}
                        disabled={feeStudentLoading || !feeStudentPagination.has_next}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                )}
              </div>
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Class billing</p><h2>Assign fee to a class</h2></div></div>
                <p className="muted panel-intro">
                  Creates a separate invoice for each active student in the class.
                  Existing invoices for the same fee structure and year are skipped.
                </p>
                <form className="form-stack" onSubmit={handleAssignClassFees}>
                  <label>
                    Class
                    <select
                      name="class_name"
                      value={classFeeInvoiceClass}
                      onChange={(event) => {
                        setClassFeeInvoiceClass(event.target.value)
                        setClassFeeTypeId('')
                      }}
                      required
                    >
                      <option value="" disabled>
                        {feeReferencesLoading
                          ? 'Loading classes...'
                          : feeManagementClasses.length
                            ? 'Select class'
                            : 'No classes found'}
                      </option>
                      {feeManagementClasses.map((className) => (
                        <option key={className} value={className}>{className}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Fee structure
                    <select
                      name="fee_type_id"
                      value={classFeeTypeId}
                      onChange={(event) => setClassFeeTypeId(event.target.value)}
                      required
                    >
                      <option value="" disabled>Select fee structure</option>
                      {classAssignableFeeTypes.map((feeType) => (
                        <option key={feeType.id} value={feeType.id}>
                          {feeType.name} · {formatCurrency(feeType.amount)}
                          {feeType.class_name ? ` · ${feeType.class_name}` : ''}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Academic year
                    <select
                      name="academic_year_id"
                      defaultValue={academicYears.find((year) => year.is_current)?.id || ''}
                      required
                    >
                      {academicYears.map((year) => (
                        <option key={year.id} value={year.id}>{year.name}</option>
                      ))}
                    </select>
                  </label>
                  <div className="field-row">
                    <label>
                      Override amount <span className="optional">(optional)</span>
                      <input name="amount" type="number" min="0.01" step="0.01" />
                    </label>
                    <label>
                      Due date
                      <input name="due_date" type="date" required />
                    </label>
                  </div>
                  <button
                    className="primary-button"
                    disabled={
                      feeLoading ||
                      feeReferencesLoading ||
                      feeTypesLoading ||
                      !feeManagementClasses.length ||
                      !classAssignableFeeTypes.length
                    }
                  >
                    {feeLoading ? 'Assigning...' : 'Assign to class'}
                  </button>
                </form>
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div><p className="eyebrow">Fee ledger</p><h2>Invoices and payments</h2></div>
                <span className="count-pill">
                  {feeInvoicePagination?.total_records ?? filteredFeeInvoices.length} invoices
                </span>
              </div>
              <div className="filter-row">
                <label>
                  Search invoices
                  <input
                    type="search"
                    value={feeInvoiceSearch}
                    onChange={(event) => {
                      setFeeInvoiceSearch(event.target.value)
                      setFeeInvoiceLoading(true)
                      setFeeInvoices([])
                      setFeeInvoicePagination(null)
                      setFeeInvoiceSummary(null)
                    }}
                    maxLength="120"
                    placeholder="Student name, admission number, or invoice ID"
                  />
                </label>
                <label>
                  Payment status
                  <select
                    value={feeStatusFilter}
                    onChange={(event) => {
                      setFeeStatusFilter(event.target.value)
                      setFeeInvoicePage(1)
                      setFeeInvoiceLoading(true)
                      setFeeInvoices([])
                      setFeeInvoicePagination(null)
                      setFeeInvoiceSummary(null)
                    }}
                  >
                    <option value="all">All statuses</option>
                    <option value="paid">Paid</option>
                    <option value="partially_paid">Partially paid</option>
                    <option value="pending">Pending</option>
                    <option value="overdue">Overdue</option>
                    <option value="waived">Waived</option>
                  </select>
                </label>
                <label>
                  Class
                  <select
                    value={feeClassFilter}
                    onChange={(event) => {
                      setFeeClassFilter(event.target.value)
                      setFeeInvoicePage(1)
                      setFeeInvoiceLoading(true)
                      setFeeInvoices([])
                      setFeeInvoicePagination(null)
                      setFeeInvoiceSummary(null)
                    }}
                  >
                    <option value="all">All classes</option>
                    {feeManagementClasses.map((className) => (
                      <option key={className} value={className}>{className}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="field-row">
                <label>
                  Payment method for recorded payments
                  <select
                    value={invoicePaymentMethod}
                    onChange={(event) => setInvoicePaymentMethod(event.target.value)}
                  >
                    {PAYMENT_METHODS.map((method) => (
                      <option key={method} value={method}>{method.replace('_', ' ')}</option>
                    ))}
                  </select>
                </label>
              </div>
              {feeInvoiceError && (
                <p className="inline-hint" role="alert">
                  {feeInvoiceError}{' '}
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setFeeInvoiceRefreshVersion((version) => version + 1)}
                  >
                    Retry
                  </button>
                </p>
              )}
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Student</th><th>ID / class</th><th>Fee</th><th>Total</th><th>Paid</th><th>Pending</th><th>Due date</th><th>Status</th><th>Actions</th></tr></thead>
                  <tbody>
                    {filteredFeeInvoices.map((invoice) => (
                      <tr key={invoice.id}>
                        <td>{invoice.student_name}</td><td>{invoice.admission_number}<small>{invoice.class_name || '-'}</small></td>
                        <td>{invoice.fee_name}</td><td>{formatCurrency(invoice.amount)}</td><td>{formatCurrency(invoice.paid_amount)}</td><td>{formatCurrency(invoice.pending_amount)}</td><td>{formatDate(invoice.due_date)}</td>
                        <td><span className={`status-pill ${invoice.payment_status}`}>{invoice.payment_status.replace('_', ' ')}</span></td>
                        <td><div className="table-actions">{Number(invoice.pending_amount) > 0 && invoice.payment_status !== 'waived' ? <button className="text-button" onClick={() => handlePayInvoice(invoice)}>Record payment</button> : <span className="muted">Paid in full</span>}<button className="text-button" onClick={() => handleLoadInvoicePayments(invoice)}>History</button></div></td>
                      </tr>
                    ))}
                    {filteredFeeInvoices.length === 0 && (
                      <tr>
                        <td colSpan="9">
                          {feeInvoiceLoading
                            ? 'Loading invoices...'
                            : feeInvoiceError
                              ? 'Invoices could not be loaded.'
                              : 'No invoices match these filters.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {feeInvoicePagination && feeInvoicePagination.total_records > 0 && (
                <PaginationControls
                  pagination={feeInvoicePagination}
                  onPageChange={(page) => {
                    setFeeInvoiceLoading(true)
                    setFeeInvoicePage(page)
                  }}
                  disabled={feeInvoiceLoading}
                />
              )}
              {selectedInvoice && (
                <div className="invoice-history">
                  <div className="panel-heading"><div><p className="eyebrow">Payment history</p><h3>{selectedInvoice.student_name} · {selectedInvoice.fee_name}</h3></div><button className="text-button" onClick={() => setSelectedInvoice(null)}>Close</button></div>
                  {invoicePayments.length === 0 ? <p className="empty-state">No payments recorded for this invoice.</p> : (
                    <div className="table-wrap"><table><thead><tr><th>Paid at</th><th>Amount</th><th>Method</th><th>Reference</th><th>Received by</th><th>Receipt</th></tr></thead><tbody>
                      {invoicePayments.map((payment) => <tr key={payment.id}><td>{new Date(payment.paid_at).toLocaleString()}</td><td>{formatCurrency(payment.amount)}</td><td>{payment.payment_method.replace('_', ' ')}</td><td>{payment.transaction_reference || '-'}</td><td>{payment.received_by_username}</td><td><button className="text-button" onClick={() => handleReceipt(payment.id)}>Preview</button></td></tr>)}
                    </tbody></table></div>
                  )}
                </div>
              )}
              {selectedReceipt && (
                <div className="receipt-preview">
                  <div className="panel-heading"><div><p className="eyebrow">Receipt preview</p><h3>Receipt #{selectedReceipt.id}</h3></div><button className="text-button" onClick={() => setSelectedReceipt(null)}>Close</button></div>
                  <p><strong>{selectedReceipt.student_name}</strong> · {selectedReceipt.admission_number} · {selectedReceipt.class_name}</p>
                  <p>{selectedReceipt.fee_name} · Invoice #{selectedReceipt.invoice_id}</p>
                  <p>Paid {formatCurrency(selectedReceipt.amount)} by {selectedReceipt.payment_method} on {new Date(selectedReceipt.paid_at).toLocaleString()}</p>
                  <p>Invoice total {formatCurrency(selectedReceipt.invoice_amount)} · Total paid {formatCurrency(selectedReceipt.paid_amount)} · Balance remaining {formatCurrency(selectedReceipt.balance)}</p>
                  <p>Reference: {selectedReceipt.transaction_reference || '—'}</p>
                  <button className="secondary-button" onClick={() => window.print()}>Print receipt</button>
                </div>
              )}
            </section>
          </section>
        )}

        {activeTab === 'payroll' && (
          <section className="analytics-dashboard">
            <div className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Salary management</p><h2>Monthly payroll</h2></div><span className="count-pill">{payrollPagination?.total_records ?? payroll.length} staff</span></div>
              <div className="filter-row payroll-toolbar">
                <label>Payroll month<input type="month" value={selectedPayrollMonth} onChange={(event) => { setPayrollPage(1); setPayrollLoading(true); setSelectedPayrollMonth(event.target.value) }} /></label>
                <label>Search staff<input value={payrollSearch} onChange={(event) => setPayrollSearch(event.target.value)} placeholder="Name, employee no., department" /></label>
                <button className="primary-button" onClick={handleGeneratePayroll} disabled={payrollLoading}>{payrollLoading ? 'Working...' : 'Generate monthly payroll'}</button>
              </div>
              <div className="analytics-cards payroll-summary">
                <article className="analytics-card"><span>Monthly net payroll</span><strong>{formatCurrency(payrollSummary?.net_amount ?? payroll.reduce((sum, item) => sum + Number(item.net_amount), 0))}</strong></article>
                <article className="analytics-card"><span>Paid</span><strong>{payrollSummary?.paid_count ?? payroll.filter((item) => item.status === 'paid').length}</strong></article>
                <article className="analytics-card"><span>Pending</span><strong>{payrollSummary?.pending_count ?? payroll.filter((item) => item.status === 'pending').length}</strong></article>
              </div>
              {payrollLoading ? <p className="empty-state">Loading payroll...</p> : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Employee</th><th>ID / role</th><th>Basic salary</th><th>Allowances</th><th>Deductions</th><th>Net salary</th><th>Month</th><th>Status</th><th>Actions</th></tr></thead>
                    <tbody>
                      {payroll.map((item) => (
                        <tr key={item.id}>
                          <td>{item.employee_name}</td><td>{item.employee_number}<small>{item.staff_type === 'teacher' ? 'Teacher' : 'Non-teaching staff'}</small></td>
                          <td>{formatCurrency(item.gross_amount)}</td><td>{formatCurrency(item.allowances)}</td><td>{formatCurrency(item.deductions)}</td><td>{formatCurrency(item.net_amount)}</td><td>{formatDate(item.pay_period)}</td>
                          <td><span className={`status-pill ${item.status}`}>{item.status}</span></td>
                          <td><div className="table-actions">{item.status === 'pending' && <><button className="text-button" onClick={() => handleEditPayroll(item)}>Adjust</button><button className="text-button" onClick={() => handleMarkSalaryPaid(item)}>Mark paid</button></>}</div></td>
                        </tr>
                      ))}
                      {payroll.length === 0 && <tr><td colSpan="9">No payroll records for this month. Generate payroll to create them.</td></tr>}
                    </tbody>
                  </table>
                </div>
              )}
              <PaginationControls pagination={payrollPagination} onPageChange={setPayrollPage} disabled={payrollLoading} />
            </div>
            <div className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Payroll trends</p><h2>Monthly salary expenses</h2></div></div>
              <div className="analytics-bars">
                {(adminCharts.salary_expenses || []).length === 0 ? <p className="empty-state">No paid salary records yet.</p> : (adminCharts.salary_expenses || []).map((item) => {
                  const max = Math.max(1, ...adminCharts.salary_expenses.map((row) => Number(row.amount)))
                  return <div className="analytics-bar-row" key={item.month}><div><span>{item.month}</span><strong>{formatCurrency(item.amount)}</strong></div><div className="analytics-bar"><span style={{ width: `${(Number(item.amount) / max) * 100}%` }} /></div></div>
                })}
              </div>
            </div>
          </section>
        )}

        {activeTab === 'performance' && (
          <section className="analytics-dashboard">
            <section className="content-grid">
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Assessment entry</p><h2>Record student performance</h2></div></div>
                <form className="form-stack" onSubmit={handleCreateAssessment}>
                  <label>Search student<input value={performanceStudentSearch} onChange={(event) => setPerformanceStudentSearch(event.target.value)} placeholder="Name or admission number" /></label>
                  <label>Student<select name="student_id" defaultValue="" required><option value="" disabled>Select student</option>{performanceStudentOptions.map((student) => <option key={student.id} value={student.id}>{student.name} · {student.admission_number}</option>)}</select></label>
                  <label>Course<select name="course_id" defaultValue="" required><option value="" disabled>Select course</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.course_code} · {course.name}</option>)}</select></label>
                  <label>Academic year<select name="academic_year_id" defaultValue={academicYears.find((year) => year.is_current)?.id || ''} required>{academicYears.map((year) => <option key={year.id} value={year.id}>{year.name}</option>)}</select></label>
                  <label>Exam name<input name="exam_name" maxLength="150" required placeholder="Mid-term examination" /></label>
                  <div className="field-row"><label>Marks obtained<input name="marks_obtained" type="number" min="0" step="0.01" required /></label><label>Total marks<input name="total_marks" type="number" min="0.01" step="0.01" required /></label></div>
                  <button className="primary-button" disabled={performanceLoading}>{performanceLoading ? 'Saving...' : 'Save result'}</button>
                </form>
              </div>
              <div className="panel">
                <div className="panel-heading"><div><p className="eyebrow">Top performers</p><h2>Highest course averages</h2></div></div>
                {(adminCharts.top_students || []).length === 0 ? <p className="empty-state">Enter assessment results to see student performance.</p> : <div className="activity-list">{adminCharts.top_students.map((student, index) => <div className="activity-item" key={student.student_id}><strong>{index + 1}. {student.student_name}</strong><span>{student.class_name || 'Unassigned class'} · {student.percentage}% average</span></div>)}</div>}
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Academic reports</p><h2>Performance records</h2></div><span className="count-pill">{filteredPerformance.length} results</span></div>
              <div className="filter-row">
                <label>Class<select value={performanceClassFilter} onChange={(event) => setPerformanceClassFilter(event.target.value)}><option value="all">All classes</option>{studentClasses.map((className) => <option key={className} value={className}>{className}</option>)}</select></label>
                <label>Course<select value={performanceCourseFilter} onChange={(event) => setPerformanceCourseFilter(event.target.value)}><option value="all">All courses</option>{courses.map((course) => <option key={course.id} value={course.id}>{course.course_code}</option>)}</select></label>
                <label>Student<select value={performanceStudentFilter} onChange={(event) => setPerformanceStudentFilter(event.target.value)}><option value="all">All students</option>{performanceStudentOptions.map((student) => <option key={student.id} value={student.id}>{student.name}</option>)}</select></label>
              </div>
              <div className="table-wrap"><table><thead><tr><th>Student</th><th>Student ID</th><th>Class</th><th>Course</th><th>Exam</th><th>Marks</th><th>Percentage</th><th>Grade</th><th>Actions</th></tr></thead><tbody>
                {filteredPerformance.map((record) => <tr key={record.id}><td>{record.student_name}</td><td>{record.admission_number}</td><td>{record.class_name || '-'}</td><td>{record.course_code}</td><td>{record.exam_name}</td><td>{record.marks_obtained} / {record.total_marks}</td><td>{record.percentage}%</td><td><strong>{record.grade}</strong></td><td><button className="text-button danger-text" onClick={() => handleDeleteAssessment(record.id)}>Delete</button></td></tr>)}
                {filteredPerformance.length === 0 && <tr><td colSpan="9">No performance records match these filters.</td></tr>}
              </tbody></table></div>
            </section>
          </section>
        )}

        {activeTab === 'events' && (
          <section className="content-grid">
            <div className="panel">
              <div className="panel-heading"><div><p className="eyebrow">School calendar</p><h2>Add upcoming event</h2></div></div>
              <form className="form-stack" onSubmit={handleCreateEvent}>
                <label>Event title<input name="title" maxLength="150" required /></label>
                <label>Description<textarea name="description" rows="3" maxLength="2000" /></label>
                <div className="field-row"><label>Starts<input name="starts_at" type="datetime-local" required /></label><label>Ends <span className="optional">(optional)</span><input name="ends_at" type="datetime-local" /></label></div>
                <button className="primary-button" disabled={eventLoading}>{eventLoading ? 'Saving...' : 'Add event'}</button>
              </form>
            </div>
            <div className="panel">
              <div className="panel-heading"><div><p className="eyebrow">Calendar</p><h2>Upcoming events</h2></div><span className="count-pill">{events.length}</span></div>
              {events.length === 0 ? <p className="empty-state">No upcoming events scheduled.</p> : <div className="activity-list">{events.map((item) => <div className="activity-item" key={item.id}><strong>{item.title}</strong><span>{new Date(item.starts_at).toLocaleString()}{item.ends_at ? ` – ${new Date(item.ends_at).toLocaleString()}` : ''}</span>{item.description && <small>{item.description}</small>}<button className="text-button danger-text" onClick={() => handleDeleteEvent(item.id)}>Delete event</button></div>)}</div>}
            </div>
          </section>
        )}

        {activeTab === 'payment' && (
          <section className="content-grid payment-grid">
            <div className="panel payment-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Fee collection</p>
                  <h2>Record a student payment</h2>
                </div>
                <span className="step-number">02</span>
              </div>
              <p className="muted panel-intro">
                Payments reduce the student's fee balance. The API prevents
                recording more than the remaining amount.
              </p>
              <div className="field-row">
                <label>
                  Search students
                  <input
                    type="search"
                    value={paymentStudentSearch}
                    onChange={(event) => {
                      setPaymentStudentSearch(event.target.value)
                      setPaymentStudentLoading(true)
                      setPaymentStudentId('')
                    }}
                    maxLength="120"
                    placeholder="Name, email, or admission number"
                  />
                </label>
                <label>
                  Class
                  <select
                    value={paymentStudentClassFilter}
                    onChange={(event) => {
                      setPaymentStudentClassFilter(event.target.value)
                      setPaymentStudentLoading(true)
                      setPaymentStudentId('')
                    }}
                  >
                    <option value="all">All classes</option>
                    {paymentStudentClasses.map((className) => (
                      <option key={className} value={className}>{className}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Status
                  <select
                    value={paymentStudentStatusFilter}
                    onChange={(event) => {
                      setPaymentStudentStatusFilter(event.target.value)
                      setPaymentStudentLoading(true)
                      setPaymentStudentId('')
                    }}
                  >
                    <option value="all">All statuses</option>
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                    <option value="graduated">Graduated</option>
                    <option value="withdrawn">Withdrawn</option>
                  </select>
                </label>
              </div>
              {paymentStudentError && (
                <p className="inline-hint" role="alert">{paymentStudentError}</p>
              )}
              <form className="form-stack" onSubmit={handleCreatePayment}>
                <label>
                  Student
                  <select
                    name="student_id"
                    required
                    value={paymentStudentId}
                    onChange={(event) => setPaymentStudentId(event.target.value)}
                  >
                    <option value="" disabled>
                      {paymentStudentLoading
                        ? 'Loading students...'
                        : paymentStudents.length
                          ? 'Select a student'
                          : 'No students found'}
                    </option>
                    {paymentStudents.map((student) => (
                      <option
                        key={student.id}
                        value={student.id}
                        disabled={Number(student.balance) <= 0}
                      >
                        {student.name} | {student.admission_number} | balance{' '}
                        {formatCurrency(student.balance)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="field-row">
                  <label>
                    Amount paid
                    <input
                      name="amount"
                      type="number"
                      min="0.01"
                      step="0.01"
                      placeholder="0.00"
                      required
                    />
                  </label>
                  <label>
                    Payment method
                    <select name="payment_method" defaultValue="cash" required>
                      {PAYMENT_METHODS.map((method) => (
                        <option key={method} value={method}>
                          {method.replace('_', ' ')}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Transaction reference <span className="optional">(optional)</span>
                  <input
                    name="transaction_reference"
                    maxLength="120"
                    placeholder="Receipt or bank reference"
                  />
                </label>
                <label>
                  Notes <span className="optional">(optional)</span>
                  <textarea
                    name="notes"
                    rows="3"
                    maxLength="500"
                    placeholder="Additional payment details"
                  />
                </label>
                <button
                  className="primary-button"
                  disabled={
                    paymentLoading ||
                    paymentStudentLoading ||
                    !paymentStudents.some((student) => Number(student.balance) > 0)
                  }
                >
                  {paymentLoading ? 'Recording...' : 'Record payment'}
                </button>
                {!paymentStudentLoading &&
                  !paymentStudentError &&
                  !paymentStudents.some((student) => Number(student.balance) > 0) && (
                  <p className="inline-hint">
                    No students with an outstanding balance match these filters.
                  </p>
                )}
              </form>
            </div>

            <div className="panel balance-panel">
              <p className="eyebrow">Payment overview</p>
              <h2>Current ledger</h2>
              <div className="ledger-stats">
                <div>
                  <span>Total entries</span>
                  <strong>{paymentTotalCount}</strong>
                </div>
                <div>
                  <span>Students with balance</span>
                  <strong>{outstandingCount}</strong>
                </div>
              </div>
              <button className="secondary-button" onClick={() => setActiveTab('history')}>
                View all payments
              </button>
            </div>
          </section>
        )}

        {activeTab === 'history' && (
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Fee collection</p>
                <h2>All payment entries</h2>
              </div>
              <span className="count-pill">
                {payments.length}
                {paymentHistoryPagination
                  ? ` of ${paymentHistoryPagination.total_records}`
                  : ''}{' '}
                entries
              </span>
            </div>
            <div className="filter-row">
              <label>
                Search payments
                <input
                  type="search"
                  value={paymentHistorySearch}
                  onChange={(event) => {
                    setPaymentHistorySearch(event.target.value)
                    setPaymentHistoryLoading(true)
                    setPayments([])
                    setPaymentHistoryPagination(null)
                  }}
                  maxLength="120"
                  placeholder="Student, admission number, or reference"
                />
              </label>
              <label>
                Class
                <select
                  value={paymentHistoryClassFilter}
                  onChange={(event) => {
                    setPaymentHistoryClassFilter(event.target.value)
                    setPaymentHistoryPage(1)
                    setPaymentHistoryLoading(true)
                    setPayments([])
                    setPaymentHistoryPagination(null)
                  }}
                >
                  <option value="all">All classes</option>
                  {paymentHistoryClasses.map((className) => (
                    <option key={className} value={className}>{className}</option>
                  ))}
                </select>
              </label>
              <label>
                Payment method
                <select
                  value={paymentHistoryMethodFilter}
                  onChange={(event) => {
                    setPaymentHistoryMethodFilter(event.target.value)
                    setPaymentHistoryPage(1)
                    setPaymentHistoryLoading(true)
                    setPayments([])
                    setPaymentHistoryPagination(null)
                  }}
                >
                  <option value="all">All methods</option>
                  {PAYMENT_METHODS.map((method) => (
                    <option key={method} value={method}>
                      {method.replace('_', ' ')}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {paymentHistoryError && (
              <p className="inline-hint" role="alert">{paymentHistoryError}</p>
            )}
            {payments.length === 0 ? (
              <p className="empty-state">
                {paymentHistoryLoading
                  ? 'Loading payment history...'
                  : paymentHistoryError
                    ? 'Payment history could not be loaded.'
                    : 'No payments match these filters.'}
              </p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Student</th>
                      <th>Admission no.</th>
                      <th>Amount</th>
                      <th>Method</th>
                      <th>Paid at</th>
                      <th>Reference</th>
                      <th>Recorded by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {payments.map((payment) => (
                      <tr key={payment.id}>
                        <td>
                          <strong>{payment.student_name}</strong>
                          <small>{payment.username}</small>
                        </td>
                        <td>{payment.admission_number}</td>
                        <td className="amount-cell">
                          {formatCurrency(payment.amount)}
                        </td>
                        <td>
                          <span className="method-pill">
                            {payment.payment_method.replace('_', ' ')}
                          </span>
                        </td>
                        <td>{new Date(payment.paid_at).toLocaleString()}</td>
                        <td>{payment.transaction_reference || '-'}</td>
                        <td>{payment.received_by_username}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {paymentHistoryLoading && payments.length > 0 && (
              <p className="inline-hint">Loading payment history...</p>
            )}
            {paymentHistoryPagination?.has_next && (
              <button
                className="secondary-button"
                disabled={paymentHistoryLoading}
                onClick={() => {
                  setPaymentHistoryLoading(true)
                  if (paymentHistoryError) {
                    setPaymentHistoryRefreshVersion((version) => version + 1)
                  } else {
                    setPaymentHistoryPage((page) => page + 1)
                  }
                }}
              >
                {paymentHistoryLoading
                  ? 'Loading...'
                  : paymentHistoryError
                    ? 'Retry loading more'
                    : 'Load 10 more'}
              </button>
            )}
          </section>
        )}
        {editingUser && (
          <div className="modal-backdrop" role="presentation" onClick={() => setEditingUser(null)}>
            <section className="panel edit-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-user-title" onClick={(event) => event.stopPropagation()}>
              <div className="panel-heading"><div><p className="eyebrow">User management</p><h2 id="edit-user-title">Edit {editingUser.name}</h2></div><button className="text-button" onClick={() => setEditingUser(null)}>Close</button></div>
              <form className="form-stack" onSubmit={handleSaveUser}>
                <div className="field-row"><label>First name<input name="first_name" defaultValue={editingUser.first_name} required /></label><label>Last name<input name="last_name" defaultValue={editingUser.last_name} required /></label></div>
                <div className="field-row"><label>Email<input name="email" type="email" defaultValue={editingUser.email} required /></label><label>Phone<input name="phone" defaultValue={editingUser.phone || ''} /></label></div>
                <button className="primary-button" disabled={userLoading}>{userLoading ? 'Saving...' : 'Save user'}</button>
              </form>
            </section>
          </div>
        )}
        {editingStudent && (
          <div className="modal-backdrop" role="presentation" onClick={() => setEditingStudent(null)}>
            <section className="panel edit-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-student-title" onClick={(event) => event.stopPropagation()}>
              <div className="panel-heading"><div><p className="eyebrow">Student management</p><h2 id="edit-student-title">Edit student profile</h2></div><button className="text-button" onClick={() => setEditingStudent(null)}>Close</button></div>
              <form className="form-stack" onSubmit={handleSaveStudent}>
                <div className="field-row"><label>First name<input name="first_name" defaultValue={editingStudent.name?.split(' ')[0] || ''} required /></label><label>Last name<input name="last_name" defaultValue={editingStudent.name?.split(' ').slice(1).join(' ') || ''} required /></label></div>
                <div className="field-row"><label>Email<input name="email" type="email" defaultValue={editingStudent.email || ''} required /></label><label>Phone<input name="phone" defaultValue={editingStudent.phone || ''} /></label></div>
                <div className="field-row"><label>Date of birth<input name="date_of_birth" type="date" defaultValue={String(editingStudent.date_of_birth || '').slice(0, 10)} /></label><label>Gender<input name="gender" defaultValue={editingStudent.gender || ''} /></label></div>
                <div className="field-row"><label>Class / grade<input name="class_name" defaultValue={editingStudent.class_name || ''} /></label><label>Admission date<input name="admission_date" type="date" defaultValue={String(editingStudent.admission_date || '').slice(0, 10)} required /></label></div>
                <div className="field-row"><label>Parent / guardian<input name="parent_guardian_name" defaultValue={editingStudent.parent_guardian_name || ''} /></label><label>Parent contact<input name="parent_contact" defaultValue={editingStudent.parent_contact || ''} /></label></div>
                <div className="field-row"><label>Fee amount<input name="fee_amount" type="number" min="0" step="0.01" defaultValue={editingStudent.fee_amount || 0} /></label><label>Status<select name="status" defaultValue={editingStudent.status || 'active'}><option value="active">Active</option><option value="inactive">Inactive</option><option value="graduated">Graduated</option><option value="withdrawn">Withdrawn</option></select></label></div>
                <label>Address<textarea name="address" rows="2" defaultValue={editingStudent.address || ''} /></label>
                <button className="primary-button">Save student</button>
              </form>
            </section>
          </div>
        )}
        {editingStaff && (
          <div className="modal-backdrop" role="presentation" onClick={() => setEditingStaff(null)}>
            <section className="panel edit-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-staff-title" onClick={(event) => event.stopPropagation()}>
              <div className="panel-heading"><div><p className="eyebrow">Staff management</p><h2 id="edit-staff-title">Edit {editingStaff.name}</h2></div><button className="text-button" onClick={() => setEditingStaff(null)}>Close</button></div>
              <form className="form-stack" onSubmit={handleSaveStaff}>
                <div className="field-row"><label>First name<input name="first_name" defaultValue={editingStaff.name?.split(' ')[0] || ''} required /></label><label>Last name<input name="last_name" defaultValue={editingStaff.name?.split(' ').slice(1).join(' ') || ''} required /></label></div>
                <div className="field-row"><label>Email<input name="email" type="email" defaultValue={editingStaff.email || ''} required /></label><label>Phone<input name="phone" defaultValue={editingStaff.phone || ''} /></label></div>
                <div className="field-row"><label>Designation<input name="designation" defaultValue={editingStaff.designation || ''} required /></label><label>Department<input name="department" defaultValue={editingStaff.department || ''} /></label></div>
                <div className="field-row"><label>Joining date<input name="hire_date" type="date" defaultValue={String(editingStaff.hire_date || '').slice(0, 10)} required /></label><label>Base salary<input name="base_salary" type="number" min="0" step="0.01" defaultValue={editingStaff.base_salary || 0} /></label></div>
                <div className="field-row"><label>Education / qualification<input name="education" defaultValue={editingStaff.education || ''} /></label><label>Experience (years)<input name="experience_years" type="number" min="0" step="0.1" defaultValue={editingStaff.experience_years || 0} /></label></div>
                <div className="field-row"><label>Shift<input name="shift" defaultValue={editingStaff.shift || ''} /></label><label>Status<select name="status" defaultValue={editingStaff.status || 'active'}><option value="active">Active</option><option value="inactive">Inactive</option><option value="on_leave">On leave</option><option value="terminated">Terminated</option></select></label></div>
                <label>Address<textarea name="address" rows="2" defaultValue={editingStaff.address || ''} /></label>
                <button className="primary-button">Save staff profile</button>
              </form>
            </section>
          </div>
        )}
        {studentProfile && (
          <div className="modal-backdrop" role="presentation" onClick={() => setStudentProfile(null)}>
            <section className="panel edit-dialog profile-dialog" role="dialog" aria-modal="true" aria-labelledby="student-profile-title" onClick={(event) => event.stopPropagation()}>
              <div className="panel-heading"><div><p className="eyebrow">Student record</p><h2 id="student-profile-title">{studentProfile.student.name}</h2></div><button className="text-button" onClick={() => setStudentProfile(null)}>Close</button></div>
              <div className="profile-summary"><p><strong>Student ID:</strong> {studentProfile.student.id} · <strong>Admission:</strong> {studentProfile.student.admission_number}</p><p><strong>Email:</strong> {studentProfile.student.email} · <strong>Phone:</strong> {studentProfile.student.phone || '-'}</p><p><strong>Date of birth:</strong> {formatDate(studentProfile.student.date_of_birth)} · <strong>Gender:</strong> {studentProfile.student.gender || '-'}</p><p><strong>Class:</strong> {studentProfile.student.class_name || '-'} · <strong>Status:</strong> {studentProfile.student.status}</p><p><strong>Guardian:</strong> {studentProfile.student.parent_guardian_name || '-'} · <strong>Parent contact:</strong> {studentProfile.student.parent_contact || '-'}</p><p><strong>Address:</strong> {studentProfile.student.address || '-'}</p></div>
              <div className="analytics-cards"><article className="analytics-card"><span>Attendance records</span><strong>{studentProfile.attendance?.total || 0}</strong></article><article className="analytics-card"><span>Present</span><strong>{studentProfile.attendance?.present || 0}</strong></article><article className="analytics-card"><span>Pending fees</span><strong>{formatCurrency(studentProfile.fee_status?.pending_balance)}</strong></article></div>
              <h3>Course enrollment</h3><div className="activity-list">{studentProfile.courses.map((course) => <div className="activity-item" key={`${course.id}-${course.academic_year_id}`}><strong>{course.course_code} · {course.name}</strong><span>{course.academic_year} · {course.enrollment_status}</span></div>)}</div>
              <h3>Performance</h3><div className="activity-list">{studentProfile.performance.map((record, index) => <div className="activity-item" key={`${record.exam_name}-${index}`}><strong>{record.exam_name} · {record.course_code}</strong><span>{record.marks_obtained} / {record.total_marks} · {record.percentage}%</span></div>)}</div>
            </section>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
