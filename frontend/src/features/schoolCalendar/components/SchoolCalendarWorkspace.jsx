import { CalendarDays, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import EmptyState from "../../../components/shared/EmptyState";
import LoadingState from "../../../components/shared/LoadingState";
import Badge from "../../../components/ui/Badge";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import Modal from "../../../components/ui/Modal";
import { useToast } from "../../../hooks/useToast";
import { academicService } from "../../../services/academicService";
import { getErrorMessage, isAbortError } from "../../../services/api";
import {
  CheckboxControl,
  SelectControl,
  WorkspacePanel,
} from "../../academic-admin/AcademicWorkspacePrimitives";
import { schoolCalendarService } from "../api/schoolCalendarService";
import { dayTypeLabel, formatCalendarDate } from "../utils/calendarDisplay";
import { getCalendarErrorMessage } from "../utils/calendarErrorMessages";
import CalendarEventCard from "./CalendarEventCard";
import CalendarStatusBadge from "./CalendarStatusBadge";

const asItems = (response) =>
  Array.isArray(response?.items) ? response.items : [];
const todayIso = () => new Date().toISOString().slice(0, 10);
const addDays = (isoDate, days) => {
  const date = new Date(`${isoDate}T00:00:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
};

const formatTermName = (term) =>
  String(term?.display_name || term?.name || "Term").replaceAll("_", " ");
const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());

const calendarLabel = (calendar, sessions = [], terms = []) => {
  if (!calendar) return "Calendar";
  const session = sessions.find(
    (item) => item.id === calendar.academic_session_id,
  );
  const term = terms.find((item) => item.id === calendar.academic_term_id);
  const sessionName = session?.name || "Selected session";
  const termName = formatTermName(term);
  return `${sessionName} - ${termName} - ${titleCase(calendar.status || "draft")}`;
};

const generationResultMessage = (result) => {
  const created = Number(result?.generated_days_created || 0);
  const updated = Number(result?.generated_days_updated || 0);
  if (!created && !updated) return "Calendar is already up to date.";
  return `Calendar updated. ${result.instructional_days} school day${Number(result.instructional_days) === 1 ? "" : "s"} and ${result.weekend_days} weekend day${Number(result.weekend_days) === 1 ? "" : "s"} are ready. Manual changes were preserved.`;
};

export const CLOSED_DAY_TYPES = new Set([
  "weekend",
  "public_holiday",
  "school_holiday",
  "mid_term_break",
  "emergency_closure",
]);

export const applyDayTypeToForm = (current, dayType, overrides = {}) => {
  const next = {
    ...current,
    ...overrides,
    day_type: dayType,
  };

  if (!CLOSED_DAY_TYPES.has(dayType)) return next;

  return {
    ...next,
    opens_at: "",
    closes_at: "",
    school_open: false,
    student_activity_allowed: false,
    student_attendance_required: false,
    workforce_attendance_required: false,
  };
};

export const buildDayUpdatePayload = (dayForm, selectedCalendarId) => {
  const closed = CLOSED_DAY_TYPES.has(dayForm.day_type);

  return {
    calendar_id: selectedCalendarId,
    ...dayForm,
    opens_at: closed ? null : dayForm.opens_at || null,
    closes_at: closed ? null : dayForm.closes_at || null,
    school_open: closed ? false : dayForm.school_open,
    student_activity_allowed: closed ? false : dayForm.student_activity_allowed,
    student_attendance_required: closed
      ? false
      : dayForm.student_attendance_required,
    workforce_attendance_required: closed
      ? false
      : dayForm.workforce_attendance_required,
    historical_correction_confirmed: Boolean(dayForm.reason),
  };
};

function SchoolCalendarWorkspace({
  activeTab = "manage",
  onSaved,
  setupTermId,
}) {
  const { showSuccess, showError } = useToast();
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [calendars, setCalendars] = useState([]);
  const [days, setDays] = useState([]);
  const [events, setEvents] = useState([]);
  const [configuration, setConfiguration] = useState(null);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [selectedTermId, setSelectedTermId] = useState("");
  const [selectedCalendarId, setSelectedCalendarId] = useState("");
  const [rangeStart, setRangeStart] = useState(todayIso());
  const [rangeEnd, setRangeEnd] = useState(addDays(todayIso(), 34));
  const [loading, setLoading] = useState(true);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [saving, setSaving] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const returnToOverview = () => {
    if (saving) return;
    const next = new URLSearchParams(searchParams);
    next.set("view", "overview");
    next.delete("tab");
    setSearchParams(next, { replace: true });
  };
  const [error, setError] = useState("");
  const [configForm, setConfigForm] = useState({
    timezone: "Africa/Lagos",
    instructional_weekdays: [0, 1, 2, 3, 4],
    default_open_time: "08:00",
    default_close_time: "15:00",
    default_student_attendance_required: true,
    default_workforce_attendance_required: true,
  });
  const [closureForm, setClosureForm] = useState({
    start_date: todayIso(),
    end_date: todayIso(),
    reason: "",
  });
  const [eventForm, setEventForm] = useState({
    title: "",
    description: "",
    event_type: "academic",
    audience: "all",
    is_all_day: false,
    starts_at: `${todayIso()}T08:00`,
    ends_at: `${todayIso()}T09:00`,
    location: "",
  });
  const [eventStatus, setEventStatus] = useState("");
  const [eventAudience, setEventAudience] = useState("");
  const [editingEventId, setEditingEventId] = useState("");
  const [editingDay, setEditingDay] = useState(null);
  const [regenerationPreview, setRegenerationPreview] = useState(null);
  const [cancelEventTarget, setCancelEventTarget] = useState(null);
  const [cancelEventReason, setCancelEventReason] = useState("");
  const [dayForm, setDayForm] = useState({
    day_type: "instructional_day",
    title: "",
    description: "",
    school_open: true,
    student_activity_allowed: true,
    student_attendance_required: true,
    workforce_attendance_required: true,
    opens_at: "08:00",
    closes_at: "15:00",
    reason: "",
  });

  const selectedCalendar =
    calendars.find((item) => item.id === selectedCalendarId) || null;
  const selectedSession =
    sessions.find((item) => item.id === selectedSessionId) || null;
  const selectedTerm = terms.find((item) => item.id === selectedTermId) || null;
  const filteredTerms = useMemo(
    () =>
      terms.filter(
        (term) =>
          !selectedSessionId || term.academic_session_id === selectedSessionId,
      ),
    [selectedSessionId, terms],
  );
  const filteredCalendars = useMemo(
    () =>
      calendars.filter(
        (calendar) =>
          !selectedTermId || calendar.academic_term_id === selectedTermId,
      ),
    [calendars, selectedTermId],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const controller = new AbortController();
    try {
      const [sessionResponse, termResponse, calendarResponse, configResponse] =
        await Promise.all([
          academicService.listSessions({ limit: 100 }),
          academicService.listTerms({ limit: 100 }),
          schoolCalendarService.listAdminCalendars(
            { limit: 100 },
            { signal: controller.signal },
          ),
          schoolCalendarService
            .getConfiguration({ signal: controller.signal })
            .catch((err) => {
              if (err?.response?.status === 404) return null;
              throw err;
            }),
        ]);
      const termItems = setupTermId
        ? asItems(termResponse).filter((item) => item.id === setupTermId)
        : asItems(termResponse);
      const sessionItems = setupTermId
        ? asItems(sessionResponse).filter(
            (item) => item.id === termItems[0]?.academic_session_id,
          )
        : asItems(sessionResponse);
      const calendarItems = setupTermId
        ? asItems(calendarResponse).filter(
            (item) => item.academic_term_id === setupTermId,
          )
        : asItems(calendarResponse);
      const currentSession =
        sessionItems.find((item) => item.is_current) ||
        sessionItems.find((item) => item.status === "open") ||
        (setupTermId ? sessionItems[0] : null) ||
        null;
      const validTerms = termItems.filter(
        (item) =>
          !currentSession || item.academic_session_id === currentSession.id,
      );
      const currentTerm =
        validTerms.find((item) => item.is_current) ||
        validTerms.find((item) => item.status !== "closed") ||
        validTerms[0] ||
        null;
      const currentCalendar =
        calendarItems.find(
          (item) => item.academic_term_id === currentTerm?.id,
        ) || null;

      setSessions(sessionItems);
      setTerms(termItems);
      setCalendars(calendarItems);
      setConfiguration(configResponse);
      setSelectedSessionId((value) =>
        sessionItems.some((item) => item.id === value)
          ? value
          : currentSession?.id || "",
      );
      setSelectedTermId((value) => {
        const term = termItems.find((item) => item.id === value);
        return term &&
          (!currentSession || term.academic_session_id === currentSession.id)
          ? value
          : currentTerm?.id || "";
      });
      setSelectedCalendarId((value) => {
        const calendar = calendarItems.find((item) => item.id === value);
        return calendar &&
          (!currentTerm || calendar.academic_term_id === currentTerm.id)
          ? value
          : currentCalendar?.id || "";
      });
      if (configResponse) {
        setConfigForm({
          timezone: configResponse.timezone || "Africa/Lagos",
          instructional_weekdays: configResponse.instructional_weekdays || [
            0, 1, 2, 3, 4,
          ],
          default_open_time: configResponse.default_open_time || "08:00",
          default_close_time: configResponse.default_close_time || "15:00",
          default_student_attendance_required:
            configResponse.default_student_attendance_required,
          default_workforce_attendance_required:
            configResponse.default_workforce_attendance_required,
        });
      }
    } catch (err) {
      if (!isAbortError(err))
        setError(getErrorMessage(err, "We couldn't load the school calendar."));
    } finally {
      setLoading(false);
    }
  }, [setupTermId]);

  const loadCalendarDetails = useCallback(async () => {
    if (!selectedCalendarId) {
      setDays([]);
      setEvents([]);
      return;
    }
    setDetailsLoading(true);
    try {
      const [dayResponse, eventResponse] = await Promise.all([
        schoolCalendarService.getDays({
          calendar_id: selectedCalendarId,
          start_date: rangeStart,
          end_date: rangeEnd,
        }),
        schoolCalendarService.getAdminEvents({
          calendar_id: selectedCalendarId,
          start_date: rangeStart,
          end_date: rangeEnd,
          status: eventStatus || undefined,
          audience: eventAudience || undefined,
        }),
      ]);
      setDays(asItems(dayResponse));
      setEvents(asItems(eventResponse));
    } catch (err) {
      if (!isAbortError(err))
        setError(getErrorMessage(err, "We couldn't load the calendar days."));
    } finally {
      setDetailsLoading(false);
    }
  }, [eventAudience, eventStatus, rangeEnd, rangeStart, selectedCalendarId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadCalendarDetails();
  }, [loadCalendarDetails]);

  useEffect(() => {
    if (!selectedSessionId) return;
    const term = terms.find((item) => item.id === selectedTermId);
    if (term && term.academic_session_id === selectedSessionId) return;
    const validTerms = terms.filter(
      (item) => item.academic_session_id === selectedSessionId,
    );
    const nextTerm =
      validTerms.find((item) => item.is_current) ||
      validTerms.find((item) => item.status !== "closed") ||
      validTerms[0] ||
      null;
    setSelectedTermId(nextTerm?.id || "");
  }, [selectedSessionId, selectedTermId, terms]);

  useEffect(() => {
    if (!selectedTermId) {
      setSelectedCalendarId("");
      return;
    }
    const calendar = calendars.find((item) => item.id === selectedCalendarId);
    if (calendar && calendar.academic_term_id === selectedTermId) return;
    const nextCalendar =
      calendars.find((item) => item.academic_term_id === selectedTermId) ||
      null;
    setSelectedCalendarId(nextCalendar?.id || "");
  }, [calendars, selectedCalendarId, selectedTermId]);

  const runAction = async (busyKey, action, success) => {
    setSaving(busyKey);
    setError("");
    try {
      const result = await action();
      const successMessage =
        typeof success === "function" ? success(result) : success;
      if (successMessage) showSuccess(successMessage);
      await load();
      await loadCalendarDetails();
      await onSaved?.();
    } catch (err) {
      showError(
        getCalendarErrorMessage(
          err,
          "We couldn't complete that calendar update.",
        ),
      );
    } finally {
      setSaving("");
    }
  };

  const saveConfiguration = (event) => {
    event.preventDefault();
    runAction(
      "configuration",
      () => schoolCalendarService.updateConfiguration(configForm),
      "Calendar settings saved.",
    );
  };

  const executeGenerateCalendar = (overwriteGeneratedDays) => {
    runAction(
      "generate",
      () =>
        schoolCalendarService.generateCalendar({
          academic_session_id: selectedSessionId,
          academic_term_id: selectedTermId,
          overwrite_generated_days: overwriteGeneratedDays,
        }),
      generationResultMessage,
    ).then(() => setRegenerationPreview(null));
  };

  const generateCalendar = () => {
    const isRegeneration = Boolean(selectedCalendar?.generated_at);
    if (isRegeneration) {
      const generatedDays = days.filter(
        (day) => !day.is_manual_override,
      ).length;
      const manualOverrides = days.filter(
        (day) => day.is_manual_override,
      ).length;
      setRegenerationPreview({
        generatedDays,
        manualOverrides,
        fromRevision:
          selectedCalendar.generated_from_configuration_revision || "none",
        toRevision: configuration?.revision || "current",
      });
      return;
    }
    executeGenerateCalendar(false);
  };

  const createEmergencyClosure = (event) => {
    event.preventDefault();
    runAction(
      "closure",
      () =>
        schoolCalendarService.emergencyClosure({
          ...closureForm,
          calendar_id: selectedCalendarId || undefined,
        }),
      "Emergency closure saved.",
    );
  };

  const createEvent = (event) => {
    event.preventDefault();
    const eventPayload = {
      ...eventForm,
      starts_at: new Date(eventForm.starts_at).toISOString(),
      ends_at: new Date(eventForm.ends_at).toISOString(),
    };
    if (editingEventId) {
      runAction(
        "event",
        () => schoolCalendarService.updateEvent(editingEventId, eventPayload),
        "Calendar event updated.",
      ).then(() => setEditingEventId(""));
      return;
    }
    runAction(
      "event",
      () =>
        schoolCalendarService.createEvent({
          ...eventPayload,
          calendar_id: selectedCalendarId,
        }),
      "Calendar event saved as a draft.",
    );
  };

  const startEventEdit = (item) => {
    setEditingEventId(item.id);
    setEventForm({
      title: item.title || "",
      description: item.description || "",
      event_type: item.event_type || "academic",
      audience: item.audience || "all",
      is_all_day: Boolean(item.is_all_day),
      starts_at: String(item.starts_at || "").slice(0, 16),
      ends_at: String(item.ends_at || "").slice(0, 16),
      location: item.location || "",
    });
  };

  const resetEventForm = () => {
    setEditingEventId("");
    setEventForm({
      title: "",
      description: "",
      event_type: "academic",
      audience: "all",
      is_all_day: false,
      starts_at: `${todayIso()}T08:00`,
      ends_at: `${todayIso()}T09:00`,
      location: "",
    });
  };

  const openDayEditor = (day) => {
    setEditingDay(day);
    setDayForm({
      day_type: day.day_type || "instructional_day",
      title: day.title || "",
      description: day.description || "",
      school_open: Boolean(day.school_open),
      student_activity_allowed: Boolean(day.student_activity_allowed),
      student_attendance_required: Boolean(day.student_attendance_required),
      workforce_attendance_required: Boolean(day.workforce_attendance_required),
      opens_at: day.opens_at || "",
      closes_at: day.closes_at || "",
      reason: "",
    });
  };

  const updateDay = (event) => {
    event.preventDefault();
    if (!editingDay) return;

    const payload = buildDayUpdatePayload(dayForm, selectedCalendarId);

    runAction(
      "day",
      () => schoolCalendarService.updateDay(editingDay.calendar_date, payload),
      "Calendar day updated.",
    ).then(() => setEditingDay(null));
  };

  if (loading) return <LoadingState label="Loading school calendar..." />;

  const busy = Boolean(saving);

  return (
    <section className="space-y-4">
      {error ? <Notice tone="error" message={error} /> : null}

      {activeTab === "overview" ? (
        <OverviewTab
          selectedSession={selectedSession}
          selectedTerm={selectedTerm}
          selectedCalendar={selectedCalendar}
          configuration={configuration}
          events={events}
          days={days}
        />
      ) : null}

      {activeTab === "setup" ? (
        <SetupTab
          onBack={setupTermId ? undefined : returnToOverview}
          sessions={sessions}
          filteredTerms={filteredTerms}
          selectedSessionId={selectedSessionId}
          selectedTermId={selectedTermId}
          selectedSession={selectedSession}
          selectedTerm={selectedTerm}
          selectedCalendar={selectedCalendar}
          days={days}
          configForm={configForm}
          configuration={configuration}
          busy={busy}
          saving={saving}
          onSessionChange={setSelectedSessionId}
          onTermChange={setSelectedTermId}
          onConfigChange={setConfigForm}
          onSave={saveConfiguration}
          onGenerate={generateCalendar}
        />
      ) : null}

      {activeTab === "calendar" || activeTab === "manage" ? (
        <ManageTab
          calendars={filteredCalendars}
          sessions={sessions}
          terms={terms}
          days={days}
          detailsLoading={detailsLoading}
          selectedCalendar={selectedCalendar}
          selectedCalendarId={selectedCalendarId}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          busy={busy}
          onCalendarChange={setSelectedCalendarId}
          onRangeStartChange={setRangeStart}
          onRangeEndChange={setRangeEnd}
          onRefresh={loadCalendarDetails}
          onActivate={() =>
            runAction(
              "activate",
              () => schoolCalendarService.activateCalendar(selectedCalendar.id),
              "Calendar activated.",
            )
          }
          onArchive={() =>
            runAction(
              "archive",
              () =>
                schoolCalendarService.archiveCalendar(selectedCalendar.id, {
                  reason: "Calendar archived from admin workspace.",
                }),
              "Calendar archived.",
            )
          }
          onDayClick={openDayEditor}
        />
      ) : null}

      {activeTab === "events" ? (
        <EventsTab
          calendars={filteredCalendars}
          sessions={sessions}
          terms={terms}
          events={events}
          eventForm={eventForm}
          eventStatus={eventStatus}
          eventAudience={eventAudience}
          editingEventId={editingEventId}
          selectedCalendarId={selectedCalendarId}
          busy={busy}
          saving={saving}
          onCalendarChange={setSelectedCalendarId}
          onEventChange={setEventForm}
          onStatusChange={setEventStatus}
          onAudienceChange={setEventAudience}
          onCreate={createEvent}
          onEdit={startEventEdit}
          onCancelEdit={resetEventForm}
          onPublish={(eventId) =>
            runAction(
              "event-action",
              () => schoolCalendarService.publishEvent(eventId),
              "Calendar event published.",
            )
          }
          onCancel={(eventId) => {
            setCancelEventTarget(eventId);
            setCancelEventReason("");
          }}
        />
      ) : null}

      {activeTab === "closures" ? (
        <ClosuresTab
          onBack={returnToOverview}
          calendars={filteredCalendars}
          sessions={sessions}
          terms={terms}
          closureForm={closureForm}
          selectedCalendarId={selectedCalendarId}
          busy={busy}
          saving={saving}
          onCalendarChange={setSelectedCalendarId}
          onClosureChange={setClosureForm}
          onCreate={createEmergencyClosure}
        />
      ) : null}

      {activeTab === "history" ? (
        <WorkspacePanel
          title="History"
          description="Calendar activity history will appear here when this view is available."
        >
          <p className="text-sm text-text-muted">
            Calendar changes are recorded automatically as you update settings,
            days, closures, and events.
          </p>
        </WorkspacePanel>
      ) : null}

      {editingDay ? (
        <DayEditor
          day={editingDay}
          form={dayForm}
          busy={busy}
          saving={saving}
          onChange={setDayForm}
          onClose={() => setEditingDay(null)}
          onSubmit={updateDay}
        />
      ) : null}

      <Modal
        open={Boolean(regenerationPreview)}
        title="Regenerate calendar"
        description="Generated school days will be refreshed from the current setup. Manual day changes are preserved."
        onClose={busy ? undefined : () => setRegenerationPreview(null)}
        closeOnOverlay={!busy}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setRegenerationPreview(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => executeGenerateCalendar(true)}
            >
              {saving === "generate"
                ? "Regenerating..."
                : "Regenerate calendar"}
            </Button>
          </div>
        }
      >
        {regenerationPreview ? (
          <div className="space-y-2 text-sm text-text-muted">
            <p>
              {regenerationPreview.generatedDays} generated day
              {regenerationPreview.generatedDays === 1 ? "" : "s"} will be
              refreshed.
            </p>
            <p>
              {regenerationPreview.manualOverrides} manual change
              {regenerationPreview.manualOverrides === 1 ? "" : "s"} will stay
              unchanged.
            </p>
            <p>Your latest calendar settings will be used.</p>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(cancelEventTarget)}
        title="Cancel calendar event"
        description="The event will no longer appear as an active school event. Calendar history remains available."
        onClose={busy ? undefined : () => setCancelEventTarget(null)}
        closeOnOverlay={!busy}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setCancelEventTarget(null)}
            >
              Keep event
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={busy || cancelEventReason.trim().length < 3}
              onClick={() =>
                runAction(
                  "event-action",
                  () =>
                    schoolCalendarService.cancelEvent(
                      cancelEventTarget,
                      cancelEventReason.trim(),
                    ),
                  "Calendar event cancelled.",
                ).then(() => setCancelEventTarget(null))
              }
            >
              {saving === "event-action" ? "Cancelling..." : "Cancel event"}
            </Button>
          </div>
        }
      >
        <Input
          label="Reason"
          value={cancelEventReason}
          onChange={(event) => setCancelEventReason(event.target.value)}
          placeholder="Explain why this event is being cancelled"
        />
      </Modal>
    </section>
  );
}

function SetupTab({
  sessions,
  filteredTerms,
  selectedSessionId,
  selectedTermId,
  selectedSession,
  selectedTerm,
  selectedCalendar,
  days,
  configForm,
  configuration,
  busy,
  saving,
  onSessionChange,
  onTermChange,
  onConfigChange,
  onSave,
  onGenerate,
  onBack,
}) {
  const setupSteps = [
    ["Select session and term", selectedSessionId && selectedTermId],
    ["Validate term dates", selectedTerm?.start_date && selectedTerm?.end_date],
    ["Configure normal operating pattern", Boolean(configuration)],
    ["Generate preview", Boolean(selectedTermId)],
    ["Review generated dates", false],
    ["Add holidays and exceptions", false],
    ["Activate calendar", false],
    ["Open term", selectedCalendar?.status === "active"],
  ];
  const isRegeneration = Boolean(selectedCalendar?.generated_at);
  const generatedDays = days.filter((day) => !day.is_manual_override).length;
  const manualOverrides = days.filter((day) => day.is_manual_override).length;

  return (
    <WorkspacePanel title="Calendar Setup" onBack={onBack} backDisabled={busy}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(22rem,0.85fr)]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectControl
              label="Session"
              value={selectedSessionId}
              onChange={onSessionChange}
              options={sessions.map((session) => ({
                value: session.id,
                label: session.name,
              }))}
            />
            <SelectControl
              label="Term"
              value={selectedTermId}
              onChange={onTermChange}
              options={filteredTerms.map((term) => ({
                value: term.id,
                label: String(term.display_name || term.name).replaceAll(
                  "_",
                  " ",
                ),
              }))}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Metric
              label="Session"
              value={selectedSession?.name || "Not selected"}
            />
            <Metric label="Term" value={formatTermName(selectedTerm)} />
            <Metric
              label="Calendar"
              value={titleCase(selectedCalendar?.status || "Not generated")}
            />
          </div>

          <div className="grid gap-2 sm:grid-cols-4">
            {setupSteps.map(([label, complete], index) => {
              const current =
                !complete &&
                setupSteps.slice(0, index).every(([, done]) => done);
              return (
                <div
                  key={label}
                  className="rounded-lg border border-border/70 bg-surface px-3 py-2"
                >
                  <p className="text-xs font-semibold text-text">
                    {index + 1}. {label}
                  </p>
                  <Badge
                    className="mt-2"
                    variant={
                      complete ? "success" : current ? "warning" : "default"
                    }
                  >
                    {complete
                      ? "complete"
                      : current
                        ? "current"
                        : "not started"}
                  </Badge>
                </div>
              );
            })}
          </div>

          {isRegeneration ? (
            <div className="rounded-lg border border-warning/40 bg-warning-soft px-3 py-3 text-sm font-medium text-amber-950">
              Regeneration will update {generatedDays} generated day
              {generatedDays === 1 ? "" : "s"} and keep {manualOverrides} manual
              change{manualOverrides === 1 ? "" : "s"}. Review the details
              before continuing.
            </div>
          ) : null}

          <Button
            type="button"
            onClick={onGenerate}
            disabled={busy || !selectedSessionId || !selectedTermId}
          >
            <RefreshCw className="h-4 w-4" />
            {saving === "generate"
              ? "Generating..."
              : isRegeneration
                ? "Regenerate Calendar"
                : "Generate Calendar"}
          </Button>
        </div>

        <form className="space-y-4" onSubmit={onSave}>
          <Input
            label="Timezone"
            value={configForm.timezone || ""}
            onChange={(event) =>
              onConfigChange((current) => ({
                ...current,
                timezone: event.target.value,
              }))
            }
          />
          <WeekdayPicker
            value={configForm.instructional_weekdays}
            onChange={(instructional_weekdays) =>
              onConfigChange((current) => ({
                ...current,
                instructional_weekdays,
              }))
            }
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Opens at"
              type="time"
              value={configForm.default_open_time || ""}
              onChange={(event) =>
                onConfigChange((current) => ({
                  ...current,
                  default_open_time: event.target.value,
                }))
              }
            />
            <Input
              label="Closes at"
              type="time"
              value={configForm.default_close_time || ""}
              onChange={(event) =>
                onConfigChange((current) => ({
                  ...current,
                  default_close_time: event.target.value,
                }))
              }
            />
          </div>
          <CheckboxControl
            label="Students expected on open days"
            checked={configForm.default_student_attendance_required}
            onChange={(value) =>
              onConfigChange((current) => ({
                ...current,
                default_student_attendance_required: value,
              }))
            }
          />
          <CheckboxControl
            label="Workforce expected on open days"
            checked={configForm.default_workforce_attendance_required}
            onChange={(value) =>
              onConfigChange((current) => ({
                ...current,
                default_workforce_attendance_required: value,
              }))
            }
          />
          <Button type="submit" disabled={busy}>
            {saving === "configuration"
              ? "Saving..."
              : configuration
                ? "Save Configuration"
                : "Create Configuration"}
          </Button>
        </form>
      </div>
    </WorkspacePanel>
  );
}

function OverviewTab({
  selectedSession,
  selectedTerm,
  selectedCalendar,
  configuration,
  events,
  days,
}) {
  const missingDates = Number(
    selectedCalendar?.missing_dates ||
      selectedCalendar?.dependency_counts?.missing_dates ||
      0,
  );
  const invalidDays = Number(
    selectedCalendar?.invalid_days ||
      selectedCalendar?.dependency_counts?.invalid_days ||
      0,
  );
  const manualOverrides = days.filter((day) => day.is_manual_override).length;
  const coverageTotal =
    Number(selectedCalendar?.dependency_counts?.days || days.length || 0) +
    missingDates;
  const coverage = coverageTotal
    ? Math.round(((coverageTotal - missingDates) / coverageTotal) * 100)
    : 0;
  const nextAction = !configuration
    ? "Create configuration"
    : !selectedCalendar
      ? "Generate preview"
      : selectedCalendar.configuration_outdated
        ? "Regenerate generated dates"
        : selectedCalendar.can_activate
          ? "Activate calendar"
          : selectedTerm?.status === "draft" &&
              selectedCalendar.status === "active"
            ? "Open term"
            : "Review blockers";

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
      <WorkspacePanel
        title="Calendar Overview"
        description="Operational readiness for the selected session and term."
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <Metric
            label="Selected session"
            value={selectedSession?.name || "No session selected"}
          />
          <Metric label="Selected term" value={formatTermName(selectedTerm)} />
          <Metric
            label="Calendar label"
            value={
              selectedCalendar
                ? calendarLabel(
                    selectedCalendar,
                    selectedSession ? [selectedSession] : [],
                    selectedTerm ? [selectedTerm] : [],
                  )
                : "No calendar"
            }
          />
          <Metric
            label="Session status"
            value={titleCase(selectedSession?.status || "unknown")}
          />
          <Metric
            label="Term status"
            value={titleCase(selectedTerm?.status || "unknown")}
          />
          <Metric
            label="Calendar status"
            value={titleCase(selectedCalendar?.status || "not generated")}
          />
          <Metric
            label="Configuration status"
            value={
              configuration
                ? `Revision ${configuration.revision}`
                : "No configuration"
            }
          />
          <Metric label="Coverage" value={`${coverage}%`} />
          <Metric label="Missing dates" value={missingDates} />
          <Metric label="Invalid dates" value={invalidDays} />
          <Metric label="Manual overrides" value={manualOverrides} />
          <Metric label="Upcoming events" value={events.length} />
        </div>
      </WorkspacePanel>
      <WorkspacePanel
        title="Next Required Action"
        description="Resolve blockers in order before opening the term."
      >
        <p className="text-lg font-semibold text-text">{nextAction}</p>
        <div className="mt-4 space-y-2">
          {selectedCalendar?.blocker_messages?.length ? (
            selectedCalendar.blocker_messages.map((message) => (
              <div
                key={message}
                className="rounded-xl border border-warning/30 bg-warning-soft px-3 py-2 text-sm font-medium text-amber-950"
              >
                {message}
              </div>
            ))
          ) : (
            <p className="text-sm text-text-muted">
              Nothing is blocking this calendar.
            </p>
          )}
        </div>
      </WorkspacePanel>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-border/70 bg-surface px-3 py-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-semibold text-text">{value}</p>
    </div>
  );
}

function ManageTab({
  calendars,
  sessions,
  terms,
  days,
  detailsLoading,
  selectedCalendar,
  selectedCalendarId,
  rangeStart,
  rangeEnd,
  busy,
  onCalendarChange,
  onRangeStartChange,
  onRangeEndChange,
  onRefresh,
  onActivate,
  onArchive,
  onDayClick,
}) {
  return (
    <div className="space-y-4">
      <WorkspacePanel title="Calendar">
        {!selectedCalendar ? (
          <EmptyState icon={CalendarDays} title="No calendar generated" />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
              <SelectControl
                label="Calendar"
                value={selectedCalendarId}
                onChange={onCalendarChange}
                options={calendars.map((calendar) => ({
                  value: calendar.id,
                  label: calendarLabel(calendar, sessions, terms),
                }))}
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  className="manual-refresh-action"
                  onClick={onRefresh}
                  disabled={busy || detailsLoading}
                >
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </Button>
                <Button
                  type="button"
                  size="small"
                  onClick={onActivate}
                  disabled={busy || !selectedCalendar.can_activate}
                >
                  Activate
                </Button>
                <Button
                  type="button"
                  size="small"
                  variant="outline"
                  onClick={onArchive}
                  disabled={busy || !selectedCalendar.can_archive}
                >
                  Archive
                </Button>
              </div>
            </div>

            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.45fr)]">
              <div className="rounded-lg border border-border/70 bg-surface px-3 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <CalendarStatusBadge status={selectedCalendar.status} />
                  {selectedCalendar.can_activate ? (
                    <Badge variant="warning">Activation ready</Badge>
                  ) : null}
                  {selectedCalendar.can_archive ? (
                    <Badge variant="default">Archive available</Badge>
                  ) : null}
                  {selectedCalendar.configuration_outdated ? (
                    <Badge variant="warning">Settings changed</Badge>
                  ) : null}
                </div>
                <p className="mt-3 text-sm text-text-muted">
                  {selectedCalendar.blocker_messages?.length
                    ? selectedCalendar.blocker_messages.join(" ")
                    : "Nothing is blocking this calendar."}
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Metric
                  label="Days"
                  value={
                    selectedCalendar.dependency_counts?.days || days.length
                  }
                />
                <Metric
                  label="Missing"
                  value={selectedCalendar.missing_dates || 0}
                />
                <Metric
                  label="Invalid"
                  value={selectedCalendar.invalid_days || 0}
                />
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-[minmax(10rem,1fr)_minmax(10rem,1fr)] lg:max-w-xl">
              <Input
                label="Start"
                type="date"
                value={rangeStart}
                onChange={(event) => onRangeStartChange(event.target.value)}
              />
              <Input
                label="End"
                type="date"
                value={rangeEnd}
                onChange={(event) => onRangeEndChange(event.target.value)}
              />
            </div>

            {detailsLoading ? (
              <LoadingState label="Loading calendar days..." />
            ) : (
              <CalendarMonthView days={days} onDayClick={onDayClick} />
            )}
          </div>
        )}
      </WorkspacePanel>
    </div>
  );
}

function EventsTab({
  calendars,
  sessions,
  terms,
  events,
  eventForm,
  eventStatus,
  eventAudience,
  editingEventId,
  selectedCalendarId,
  busy,
  saving,
  onCalendarChange,
  onEventChange,
  onStatusChange,
  onAudienceChange,
  onCreate,
  onEdit,
  onCancelEdit,
  onPublish,
  onCancel,
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(20rem,0.85fr)_minmax(0,1.35fr)]">
      <WorkspacePanel
        title={editingEventId ? "Edit Event" : "Create Event"}
        description="Create or edit calendar events for the selected calendar."
      >
        <form className="space-y-4" onSubmit={onCreate}>
          <SelectControl
            label="Calendar"
            value={selectedCalendarId}
            onChange={onCalendarChange}
            options={calendars.map((calendar) => ({
              value: calendar.id,
              label: calendarLabel(calendar, sessions, terms),
            }))}
          />
          <Input
            label="Title"
            value={eventForm.title}
            onChange={(event) =>
              onEventChange((current) => ({
                ...current,
                title: event.target.value,
              }))
            }
          />
          <Input
            label="Description"
            value={eventForm.description}
            onChange={(event) =>
              onEventChange((current) => ({
                ...current,
                description: event.target.value,
              }))
            }
          />
          <SelectControl
            label="Event type"
            value={eventForm.event_type}
            onChange={(value) =>
              onEventChange((current) => ({ ...current, event_type: value }))
            }
            options={[
              "academic",
              "holiday",
              "examination",
              "meeting",
              "activity",
              "emergency",
              "other",
            ].map((value) => ({ value, label: value.replaceAll("_", " ") }))}
          />
          <SelectControl
            label="Audience"
            value={eventForm.audience}
            onChange={(value) =>
              onEventChange((current) => ({ ...current, audience: value }))
            }
            options={[
              "all",
              "tenant_admins",
              "teachers",
              "parents",
              "students",
            ].map((value) => ({ value, label: value.replaceAll("_", " ") }))}
          />
          <CheckboxControl
            label="All-day event"
            checked={eventForm.is_all_day}
            onChange={(value) =>
              onEventChange((current) => ({ ...current, is_all_day: value }))
            }
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Starts"
              type="datetime-local"
              value={eventForm.starts_at}
              onChange={(event) =>
                onEventChange((current) => ({
                  ...current,
                  starts_at: event.target.value,
                }))
              }
            />
            <Input
              label="Ends"
              type="datetime-local"
              value={eventForm.ends_at}
              onChange={(event) =>
                onEventChange((current) => ({
                  ...current,
                  ends_at: event.target.value,
                }))
              }
            />
          </div>
          <Input
            label="Location"
            value={eventForm.location}
            onChange={(event) =>
              onEventChange((current) => ({
                ...current,
                location: event.target.value,
              }))
            }
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              disabled={busy || !selectedCalendarId || !eventForm.title}
            >
              {saving === "event"
                ? "Saving..."
                : editingEventId
                  ? "Save Event"
                  : "Add Event"}
            </Button>
            {editingEventId ? (
              <Button
                type="button"
                variant="outline"
                onClick={onCancelEdit}
                disabled={busy}
              >
                Cancel Edit
              </Button>
            ) : null}
          </div>
        </form>
      </WorkspacePanel>

      <WorkspacePanel
        title="Event List"
        description="Review events in the selected date range."
      >
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <SelectControl
            label="Status"
            value={eventStatus}
            onChange={onStatusChange}
            options={[
              { value: "", label: "All statuses" },
              { value: "draft", label: "Draft" },
              { value: "published", label: "Published" },
              { value: "cancelled", label: "Cancelled" },
            ]}
          />
          <SelectControl
            label="Audience"
            value={eventAudience}
            onChange={onAudienceChange}
            options={[
              { value: "", label: "All audiences" },
              { value: "all", label: "All" },
              { value: "tenant_admins", label: "Admins" },
              { value: "teachers", label: "Teachers" },
              { value: "parents", label: "Parents" },
              { value: "students", label: "Students" },
            ]}
          />
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {events.length ? (
            events.map((event) => (
              <div key={event.id} className="space-y-2">
                <CalendarEventCard event={event} compact />
                <div className="flex flex-wrap gap-2">
                  {event.status !== "cancelled" ? (
                    <Button
                      type="button"
                      size="small"
                      variant="outline"
                      onClick={() => onEdit(event)}
                      disabled={busy}
                    >
                      Edit
                    </Button>
                  ) : null}
                  {event.status === "draft" ? (
                    <Button
                      type="button"
                      size="small"
                      onClick={() => onPublish(event.id)}
                      disabled={busy}
                    >
                      Publish
                    </Button>
                  ) : null}
                  {event.status !== "cancelled" ? (
                    <Button
                      type="button"
                      size="small"
                      variant="outline"
                      onClick={() => onCancel(event.id)}
                      disabled={busy}
                    >
                      Cancel
                    </Button>
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <p className="text-sm text-text-muted">No events in this range.</p>
          )}
        </div>
      </WorkspacePanel>
    </div>
  );
}

function ClosuresTab({
  onBack,
  calendars,
  sessions,
  terms,
  closureForm,
  selectedCalendarId,
  busy,
  saving,
  onCalendarChange,
  onClosureChange,
  onCreate,
}) {
  return (
    <WorkspacePanel
      title="Emergency Closure"
      onBack={onBack}
      backDisabled={busy}
      description="Close the school for a date range when normal operations need to stop."
    >
      <form className="max-w-3xl space-y-4" onSubmit={onCreate}>
        <SelectControl
          label="Calendar"
          value={selectedCalendarId}
          onChange={onCalendarChange}
          options={calendars.map((calendar) => ({
            value: calendar.id,
            label: calendarLabel(calendar, sessions, terms),
          }))}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input
            label="Start date"
            type="date"
            value={closureForm.start_date}
            onChange={(event) =>
              onClosureChange((current) => ({
                ...current,
                start_date: event.target.value,
              }))
            }
          />
          <Input
            label="End date"
            type="date"
            value={closureForm.end_date}
            onChange={(event) =>
              onClosureChange((current) => ({
                ...current,
                end_date: event.target.value,
              }))
            }
          />
        </div>
        <Input
          label="Reason"
          value={closureForm.reason}
          onChange={(event) =>
            onClosureChange((current) => ({
              ...current,
              reason: event.target.value,
            }))
          }
        />
        <div className="rounded-2xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm font-medium text-amber-950">
          The school will be marked closed for these dates, and student
          activities will be unavailable.
        </div>
        <Button
          type="submit"
          variant="danger"
          disabled={busy || !selectedCalendarId || !closureForm.reason}
        >
          <ShieldAlert className="h-4 w-4" />
          {saving === "closure" ? "Applying..." : "Create Emergency Closure"}
        </Button>
      </form>
    </WorkspacePanel>
  );
}

function WeekdayPicker({ value = [], onChange }) {
  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const toggle = (index) => {
    const next = value.includes(index)
      ? value.filter((item) => item !== index)
      : [...value, index].sort();
    onChange(next);
  };
  return (
    <div>
      <p className="mb-2 text-sm font-semibold text-text-soft">
        Operating weekdays
      </p>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
        {labels.map((label, index) => (
          <button
            key={label}
            type="button"
            onClick={() => toggle(index)}
            className={`min-h-10 rounded-xl border text-xs font-semibold ${value.includes(index) ? "border-primary bg-primary text-primary-foreground" : "border-border/70 bg-surface text-text-soft"}`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CalendarMonthView({ days, onDayClick }) {
  if (!days.length) {
    return <EmptyState icon={CalendarDays} title="No days in range" />;
  }
  const orderedDays = [...days].sort((left, right) =>
    String(left.calendar_date).localeCompare(String(right.calendar_date)),
  );
  const firstDate = new Date(
    `${String(orderedDays[0]?.calendar_date).slice(0, 10)}T00:00:00`,
  );
  const leadingBlankDays = Number.isNaN(firstDate.getTime())
    ? 0
    : (firstDate.getDay() + 6) % 7;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {Array.from({ length: leadingBlankDays }).map((_, index) => (
        <div
          key={`calendar-leading-blank-${index}`}
          aria-hidden="true"
          className="hidden min-h-24 xl:block"
        />
      ))}
      {orderedDays.map((day) => (
        <button
          key={day.id}
          type="button"
          onClick={() => onDayClick(day)}
          className="min-h-24 rounded-lg border border-border/70 bg-surface px-3 py-3 text-left transition hover:border-primary/50"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-semibold text-text">
              {formatCalendarDate(day.calendar_date)}
            </p>
            <CalendarStatusBadge status={day.school_open ? "active" : "closed"}>
              {day.school_open ? "Open" : "Closed"}
            </CalendarStatusBadge>
          </div>
          <p className="mt-3 text-xs font-semibold text-text-soft">
            {dayTypeLabel(day.day_type)}
          </p>
          {day.title ? (
            <p className="mt-1 line-clamp-2 text-xs text-text-muted">
              {day.title}
            </p>
          ) : null}
        </button>
      ))}
    </div>
  );
}

export function DayEditor({
  day,
  form,
  busy,
  saving,
  onChange,
  onClose,
  onSubmit,
}) {
  const presets = {
    public_holiday: {
      day_type: "public_holiday",
      title: "Public holiday",
    },
    school_holiday: {
      day_type: "school_holiday",
      title: "School holiday",
    },
    examination_day: {
      day_type: "examination_day",
      school_open: true,
      student_activity_allowed: true,
      student_attendance_required: true,
      workforce_attendance_required: true,
      title: "Examination day",
    },
    special_school_day: {
      day_type: "special_school_day",
      school_open: true,
      student_activity_allowed: true,
      student_attendance_required: true,
      workforce_attendance_required: true,
      title: "Special school day",
    },
    staff_training_day: {
      day_type: "staff_training_day",
      school_open: true,
      student_activity_allowed: false,
      student_attendance_required: false,
      workforce_attendance_required: true,
      title: "Staff training day",
    },
    weekend_school_day: {
      day_type: "special_school_day",
      school_open: true,
      student_activity_allowed: true,
      student_attendance_required: true,
      workforce_attendance_required: true,
      title: "Weekend school day",
    },
  };

  const handleDayTypeChange = (dayType, overrides = {}) => {
    onChange((current) => applyDayTypeToForm(current, dayType, overrides));
  };

  const applyPreset = (preset) => {
    const values = presets[preset];
    if (!values) return;
    handleDayTypeChange(values.day_type, values);
  };

  const isClosedDay = CLOSED_DAY_TYPES.has(form.day_type);

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/30 px-3 py-3 sm:items-center sm:justify-center">
      <form
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-surface p-4 shadow-xl sm:p-5"
        onSubmit={onSubmit}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
              Calendar day
            </p>
            <h3 className="mt-1 text-lg font-semibold text-text">
              {formatCalendarDate(day.calendar_date, { year: "numeric" })}
            </h3>
          </div>
          <Button
            type="button"
            size="small"
            variant="outline"
            onClick={onClose}
            disabled={busy}
          >
            Close
          </Button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {[
            ["public_holiday", "Public holiday"],
            ["school_holiday", "School holiday"],
            ["examination_day", "Examination day"],
            ["special_school_day", "Special day"],
            ["staff_training_day", "Staff training"],
            ["weekend_school_day", "Weekend open"],
          ].map(([value, label]) => (
            <Button
              key={value}
              type="button"
              size="small"
              variant="outline"
              onClick={() => applyPreset(value)}
            >
              {label}
            </Button>
          ))}
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <SelectControl
            label="Day type"
            value={form.day_type}
            onChange={handleDayTypeChange}
            options={[
              "instructional_day",
              "examination_day",
              "weekend",
              "public_holiday",
              "school_holiday",
              "mid_term_break",
              "staff_training_day",
              "special_school_day",
              "emergency_closure",
            ].map((value) => ({ value, label: value.replaceAll("_", " ") }))}
          />
          <Input
            label="Title"
            value={form.title}
            onChange={(event) =>
              onChange((current) => ({ ...current, title: event.target.value }))
            }
          />
        </div>

        {isClosedDay ? (
          <div className="mt-4 rounded-xl border border-border/70 bg-surface-muted px-4 py-3 text-sm text-text-muted">
            <p className="font-semibold text-text">School closed</p>
            <p className="mt-1">
              Operating hours do not apply because the school is closed. Student
              activities and attendance expectations are disabled.
            </p>
          </div>
        ) : (
          <>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Input
                label="Opens at"
                type="time"
                value={form.opens_at || ""}
                onChange={(event) =>
                  onChange((current) => ({
                    ...current,
                    opens_at: event.target.value,
                  }))
                }
              />
              <Input
                label="Closes at"
                type="time"
                value={form.closes_at || ""}
                onChange={(event) =>
                  onChange((current) => ({
                    ...current,
                    closes_at: event.target.value,
                  }))
                }
              />
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-2">
              <CheckboxControl
                label="School open"
                checked={form.school_open}
                onChange={(value) =>
                  onChange((current) => ({ ...current, school_open: value }))
                }
              />
              <CheckboxControl
                label="Student activity allowed"
                checked={form.student_activity_allowed}
                onChange={(value) =>
                  onChange((current) => ({
                    ...current,
                    student_activity_allowed: value,
                  }))
                }
              />
              <CheckboxControl
                label="Student attendance expected"
                checked={form.student_attendance_required}
                onChange={(value) =>
                  onChange((current) => ({
                    ...current,
                    student_attendance_required: value,
                  }))
                }
              />
              <CheckboxControl
                label="Staff attendance expected"
                checked={form.workforce_attendance_required}
                onChange={(value) =>
                  onChange((current) => ({
                    ...current,
                    workforce_attendance_required: value,
                  }))
                }
              />
            </div>
          </>
        )}

        <div className="mt-4 space-y-3">
          <Input
            label="Description"
            value={form.description}
            onChange={(event) =>
              onChange((current) => ({
                ...current,
                description: event.target.value,
              }))
            }
          />
          <Input
            label="Reason"
            value={form.reason}
            onChange={(event) =>
              onChange((current) => ({
                ...current,
                reason: event.target.value,
              }))
            }
          />
        </div>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {saving === "day" ? "Saving..." : "Save Day"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function Notice({ tone, message }) {
  const className =
    tone === "success"
      ? "border-success/30 bg-success-soft text-success"
      : "border-error/30 bg-error-soft text-error";
  return (
    <div
      className={`rounded-2xl border px-4 py-3 text-sm font-medium ${className}`}
    >
      {message}
    </div>
  );
}

export default SchoolCalendarWorkspace;
