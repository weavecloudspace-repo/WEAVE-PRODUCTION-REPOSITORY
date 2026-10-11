import { CalendarPlus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import LoadingState from "../../../components/shared/LoadingState";
import Button from "../../../components/ui/Button";
import Input from "../../../components/ui/Input";
import Modal from "../../../components/ui/Modal";
import { academicService } from "../../../services/academicService";
import { getErrorMessage, isAbortError } from "../../../services/api";
import {
  RecordList,
  SelectControl,
  WorkspaceGrid,
  WorkspacePanel,
} from "../../academic-admin/AcademicWorkspacePrimitives";
import { schoolCalendarService } from "../api/schoolCalendarService";
import { getCalendarErrorMessage } from "../utils/calendarErrorMessages";
import {
  buildAllDayInterval,
  inclusiveDayCount,
  inclusiveEventDateRange,
} from "../utils/eventDateUtils";

const asItems = (response) =>
  Array.isArray(response?.items) ? response.items : [];
const todayIso = () => new Date().toISOString().slice(0, 10);
const titleCase = (value) =>
  String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
const formatTermName = (term) =>
  String(term?.display_name || term?.name || "Term").replaceAll("_", " ");
const calendarLabel = (calendar, sessions, terms) => {
  const session = sessions.find(
    (item) => item.id === calendar?.academic_session_id,
  );
  const term = terms.find((item) => item.id === calendar?.academic_term_id);
  return `${session?.name || "Selected session"} · ${formatTermName(term)} · ${titleCase(
    calendar?.status || "draft",
  )}`;
};

const defaultForm = () => ({
  title: "",
  description: "",
  event_type: "academic",
  audience: "all",
  timing_mode: "specific_time",
  full_day_duration: "one_day",
  event_date: todayIso(),
  end_date: todayIso(),
  starts_at: `${todayIso()}T08:00`,
  ends_at: `${todayIso()}T09:00`,
  location: "",
});

const localDateTimeToIso = (value) => new Date(value).toISOString();

const eventDateLabel = (event) => {
  const range = inclusiveEventDateRange(event);
  if (!range) return "Date unavailable";
  if (range.start === range.end) return range.start;
  return `${range.start} → ${range.end}`;
};

function SchoolCalendarEventsWorkspace() {
  const [sessions, setSessions] = useState([]);
  const [terms, setTerms] = useState([]);
  const [calendars, setCalendars] = useState([]);
  const [events, setEvents] = useState([]);
  const [selectedCalendarId, setSelectedCalendarId] = useState("");
  const [eventStatus, setEventStatus] = useState("");
  const [eventAudience, setEventAudience] = useState("");
  const [form, setForm] = useState(defaultForm);
  const [editingEventId, setEditingEventId] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [closedDays, setClosedDays] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancelReason, setCancelReason] = useState("");

  const selectedCalendar = useMemo(
    () => calendars.find((item) => item.id === selectedCalendarId) || null,
    [calendars, selectedCalendarId],
  );

  const isFullDay = form.timing_mode === "full_day";
  const spansMultipleDays =
    isFullDay && form.full_day_duration === "multiple_days";

  const eventRange = useMemo(() => {
    if (form.timing_mode === "full_day") {
      return {
        start: form.event_date,
        end:
          form.full_day_duration === "multiple_days"
            ? form.end_date
            : form.event_date,
      };
    }
    return {
      start: String(form.starts_at || "").slice(0, 10),
      end: String(form.ends_at || "").slice(0, 10),
    };
  }, [form]);

  const spanDays = inclusiveDayCount(eventRange.start, eventRange.end);

  const loadBase = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sessionResponse, termResponse, calendarResponse] =
        await Promise.all([
          academicService.listSessions({ limit: 100 }),
          academicService.listTerms({ limit: 100 }),
          schoolCalendarService.listAdminCalendars({ limit: 100 }),
        ]);
      const sessionItems = asItems(sessionResponse);
      const termItems = asItems(termResponse);
      const calendarItems = asItems(calendarResponse);
      const currentTerm =
        termItems.find((item) => item.is_current) ||
        termItems.find((item) => item.status !== "closed");
      const currentCalendar =
        calendarItems.find(
          (item) => item.academic_term_id === currentTerm?.id,
        ) ||
        calendarItems[0] ||
        null;
      setSessions(sessionItems);
      setTerms(termItems);
      setCalendars(calendarItems);
      setSelectedCalendarId((current) =>
        calendarItems.some((item) => item.id === current)
          ? current
          : currentCalendar?.id || "",
      );
    } catch (err) {
      if (!isAbortError(err)) {
        setError(getErrorMessage(err, "Failed to load calendar events."));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const loadEvents = useCallback(async () => {
    if (!selectedCalendarId) {
      setEvents([]);
      return;
    }
    try {
      const response = await schoolCalendarService.getAdminEvents({
        calendar_id: selectedCalendarId,
        status: eventStatus || undefined,
        audience: eventAudience || undefined,
      });
      setEvents(asItems(response));
    } catch (err) {
      if (!isAbortError(err)) {
        setError(getErrorMessage(err, "Failed to load events."));
      }
    }
  }, [eventAudience, eventStatus, selectedCalendarId]);

  const inspectClosedDays = useCallback(async () => {
    if (
      !editorOpen ||
      !selectedCalendarId ||
      !eventRange.start ||
      !eventRange.end ||
      eventRange.end < eventRange.start
    ) {
      setClosedDays([]);
      return;
    }
    try {
      const response = await schoolCalendarService.getDays({
        calendar_id: selectedCalendarId,
        start_date: eventRange.start,
        end_date: eventRange.end,
      });
      setClosedDays(asItems(response).filter((day) => !day.school_open));
    } catch {
      setClosedDays([]);
    }
  }, [editorOpen, eventRange.end, eventRange.start, selectedCalendarId]);

  useEffect(() => {
    loadBase();
  }, [loadBase]);
  useEffect(() => {
    loadEvents();
  }, [loadEvents]);
  useEffect(() => {
    inspectClosedDays();
  }, [inspectClosedDays]);

  const closeEditor = () => {
    setEditingEventId("");
    setEditorOpen(false);
    setForm(defaultForm());
    setClosedDays([]);
  };

  const startCreate = () => {
    setEditingEventId("");
    setForm(defaultForm());
    setClosedDays([]);
    setEditorOpen(true);
  };

  const buildPayload = () => {
    const allDayInterval = isFullDay
      ? buildAllDayInterval({
          eventDate: form.event_date,
          spansMultipleDays,
          endDate: form.end_date,
        })
      : null;

    if (isFullDay && !allDayInterval) return null;

    return {
      title: form.title.trim(),
      description: form.description.trim() || null,
      event_type: form.event_type,
      audience: form.audience,
      is_all_day: isFullDay,
      starts_at:
        allDayInterval?.starts_at || localDateTimeToIso(form.starts_at),
      ends_at: allDayInterval?.ends_at || localDateTimeToIso(form.ends_at),
      location: form.location.trim() || null,
    };
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setMessage("");
    if (!selectedCalendarId || !form.title.trim()) return;
    if (
      !eventRange.start ||
      !eventRange.end ||
      eventRange.end < eventRange.start
    ) {
      setError("Event end must not be before its start.");
      return;
    }

    setSaving("event");
    try {
      const payload = buildPayload();
      if (!payload) throw new Error("Invalid event date range.");
      if (editingEventId) {
        await schoolCalendarService.updateEvent(editingEventId, payload);
        setMessage("Calendar event updated.");
      } else {
        await schoolCalendarService.createEvent({
          ...payload,
          calendar_id: selectedCalendarId,
        });
        setMessage("Calendar event created as draft.");
      }
      closeEditor();
      await loadEvents();
    } catch (err) {
      setError(getCalendarErrorMessage(err, "Failed to save calendar event."));
    } finally {
      setSaving("");
    }
  };

  const startEdit = (item) => {
    const range = inclusiveEventDateRange(item);
    const start = String(item.starts_at || "");
    const end = String(item.ends_at || "");
    const fullDay = Boolean(item.is_all_day);
    const multipleDays = Boolean(range && range.start !== range.end);

    setEditingEventId(item.id);
    setEditorOpen(true);
    setForm({
      title: item.title || "",
      description: item.description || "",
      event_type: item.event_type || "academic",
      audience: item.audience || "all",
      timing_mode: fullDay ? "full_day" : "specific_time",
      full_day_duration: multipleDays ? "multiple_days" : "one_day",
      event_date: range?.start || start.slice(0, 10),
      end_date: range?.end || end.slice(0, 10),
      starts_at: start.slice(0, 16),
      ends_at: end.slice(0, 16),
      location: item.location || "",
    });
  };

  const publish = async (id) => {
    setSaving(id);
    try {
      await schoolCalendarService.publishEvent(id);
      await loadEvents();
    } catch (err) {
      setError(getErrorMessage(err, "Failed to publish event."));
    } finally {
      setSaving("");
    }
  };

  const cancelEvent = async () => {
    if (!cancelTarget || cancelReason.trim().length < 3) return;
    setSaving(cancelTarget);
    try {
      await schoolCalendarService.cancelEvent(
        cancelTarget,
        cancelReason.trim(),
      );
      setCancelTarget(null);
      setCancelReason("");
      await loadEvents();
    } catch (err) {
      setError(getCalendarErrorMessage(err, "Failed to cancel event."));
    } finally {
      setSaving("");
    }
  };

  if (loading) return <LoadingState label="Loading calendar events..." />;

  return (
    <section className="space-y-4">
      {error ? <Notice tone="error" message={error} /> : null}
      {message ? <Notice tone="success" message={message} /> : null}

      <WorkspaceGrid
        content={
          <RecordList
            title="Calendar events"
            description="Scheduled school activities for the selected term calendar. Select an event to inspect it; lifecycle actions stay on the list."
            actions={
              <div className="grid w-full min-w-0 gap-2 sm:grid-cols-2">
                <SelectControl
                  label="Calendar"
                  value={selectedCalendarId}
                  onChange={setSelectedCalendarId}
                  options={calendars.map((calendar) => ({
                    value: calendar.id,
                    label: calendarLabel(calendar, sessions, terms),
                  }))}
                />
                <SelectControl
                  label="Status"
                  value={eventStatus}
                  onChange={setEventStatus}
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
                  onChange={setEventAudience}
                  options={[
                    { value: "", label: "All audiences" },
                    { value: "all", label: "All" },
                    { value: "tenant_admins", label: "Admins" },
                    { value: "teachers", label: "Teachers" },
                    { value: "parents", label: "Parents" },
                    { value: "students", label: "Students" },
                  ]}
                />
                {!editorOpen ? (
                  <Button
                    type="button"
                    onClick={startCreate}
                    disabled={!selectedCalendarId}
                  >
                    <CalendarPlus className="h-4 w-4" />
                    Create event
                  </Button>
                ) : null}
              </div>
            }
            items={events}
            emptyIcon={CalendarPlus}
            emptyTitle="No events in this calendar"
            emptyDescription="Create an event when the selected calendar has a scheduled school activity."
            renderTitle={(item) => item.title}
            renderMeta={(item) => eventDateLabel(item)}
            renderDescription={(item) =>
              [
                titleCase(item.event_type),
                titleCase(item.audience),
                item.is_all_day ? "All day" : "Timed",
                item.location,
              ]
                .filter(Boolean)
                .join(" · ")
            }
            renderStatus={(item) => item.status}
            showInspector={!editorOpen}
            renderActions={(item) => (
              <>
                {item.status !== "cancelled" ? (
                  <Button
                    type="button"
                    size="small"
                    variant="outline"
                    onClick={() => startEdit(item)}
                  >
                    Edit
                  </Button>
                ) : null}
                {item.status === "draft" ? (
                  <Button
                    type="button"
                    size="small"
                    disabled={saving === item.id}
                    onClick={() => publish(item.id)}
                  >
                    Publish
                  </Button>
                ) : null}
                {item.status !== "cancelled" ? (
                  <Button
                    type="button"
                    size="small"
                    variant="outline"
                    onClick={() => setCancelTarget(item.id)}
                  >
                    Cancel
                  </Button>
                ) : null}
              </>
            )}
          />
        }
        editor={
          editorOpen ? (
            <WorkspacePanel
              title={editingEventId ? "Edit event" : "Create event"}
              onBack={closeEditor}
              backDisabled={Boolean(saving)}
              description="Events describe scheduled activity. They do not automatically reopen or close operational school days."
            >
              <form className="space-y-4" onSubmit={submit}>
                <Input
                  label="Title"
                  value={form.title}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      title: event.target.value,
                    }))
                  }
                  required
                />
                <Input
                  label="Description"
                  value={form.description}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      description: event.target.value,
                    }))
                  }
                />
                <SelectControl
                  label="Event type"
                  value={form.event_type}
                  onChange={(value) =>
                    setForm((current) => ({ ...current, event_type: value }))
                  }
                  options={[
                    "academic",
                    "holiday",
                    "examination",
                    "meeting",
                    "activity",
                    "emergency",
                    "other",
                  ].map((value) => ({ value, label: titleCase(value) }))}
                />
                <SelectControl
                  label="Audience"
                  value={form.audience}
                  onChange={(value) =>
                    setForm((current) => ({ ...current, audience: value }))
                  }
                  options={[
                    "all",
                    "tenant_admins",
                    "teachers",
                    "parents",
                    "students",
                  ].map((value) => ({ value, label: titleCase(value) }))}
                />
                <SelectControl
                  label="Event timing"
                  value={form.timing_mode}
                  onChange={(value) =>
                    setForm((current) => ({ ...current, timing_mode: value }))
                  }
                  options={[
                    {
                      value: "specific_time",
                      label: "Specific start and end time",
                    },
                    { value: "full_day", label: "Full-day event" },
                  ]}
                />

                {isFullDay ? (
                  <div className="space-y-3">
                    <SelectControl
                      label="Duration"
                      value={form.full_day_duration}
                      onChange={(value) =>
                        setForm((current) => ({
                          ...current,
                          full_day_duration: value,
                          end_date:
                            value === "one_day"
                              ? current.event_date
                              : current.end_date || current.event_date,
                        }))
                      }
                      options={[
                        { value: "one_day", label: "One full day" },
                        { value: "multiple_days", label: "Several full days" },
                      ]}
                    />
                    {spansMultipleDays ? (
                      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                        <Input
                          label="Starts on"
                          type="date"
                          value={form.event_date}
                          onChange={(event) =>
                            setForm((current) => ({
                              ...current,
                              event_date: event.target.value,
                            }))
                          }
                        />
                        <Input
                          label="Ends on (inclusive)"
                          type="date"
                          min={form.event_date}
                          value={form.end_date}
                          onChange={(event) =>
                            setForm((current) => ({
                              ...current,
                              end_date: event.target.value,
                            }))
                          }
                        />
                      </div>
                    ) : (
                      <Input
                        label="Event date"
                        type="date"
                        value={form.event_date}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            event_date: event.target.value,
                            end_date: event.target.value,
                          }))
                        }
                      />
                    )}
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                    <Input
                      label="Starts at"
                      type="datetime-local"
                      value={form.starts_at}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          starts_at: event.target.value,
                        }))
                      }
                    />
                    <Input
                      label="Ends at"
                      type="datetime-local"
                      value={form.ends_at}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          ends_at: event.target.value,
                        }))
                      }
                    />
                  </div>
                )}

                {spanDays > 1 ? (
                  <p className="rounded-lg border border-border/70 bg-surface-muted/40 px-3 py-2 text-xs leading-5 text-text-muted">
                    Covers {spanDays} calendar days, from {eventRange.start}{" "}
                    through {eventRange.end}.
                  </p>
                ) : null}

                {closedDays.length ? (
                  <div className="rounded-lg border border-warning/40 bg-warning-soft px-3 py-3 text-xs leading-5 text-amber-950">
                    <p className="font-semibold">
                      Overlaps {closedDays.length} closed calendar day
                      {closedDays.length === 1 ? "" : "s"}.
                    </p>
                    <p className="mt-1">
                      Saving this event will not reopen school or change
                      attendance rules.
                    </p>
                  </div>
                ) : null}

                <Input
                  label="Location"
                  value={form.location}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      location: event.target.value,
                    }))
                  }
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="submit"
                    disabled={
                      Boolean(saving) || !selectedCalendar || !form.title.trim()
                    }
                  >
                    {saving === "event"
                      ? "Saving..."
                      : editingEventId
                        ? "Save event"
                        : "Create event"}
                  </Button>
                  <Button type="button" variant="outline" onClick={closeEditor}>
                    Cancel
                  </Button>
                </div>
              </form>
            </WorkspacePanel>
          ) : null
        }
      />

      <Modal
        open={Boolean(cancelTarget)}
        onClose={() => setCancelTarget(null)}
        title="Cancel event"
        placement="center"
      >
        <div className="space-y-4">
          <Input
            label="Reason"
            value={cancelReason}
            onChange={(event) => setCancelReason(event.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setCancelTarget(null)}
            >
              Keep event
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={
                cancelReason.trim().length < 3 || saving === cancelTarget
              }
              onClick={cancelEvent}
            >
              Cancel event
            </Button>
          </div>
        </div>
      </Modal>
    </section>
  );
}

function Notice({ tone, message }) {
  const className =
    tone === "success"
      ? "border-success/30 bg-success-soft text-success"
      : "border-error/30 bg-error-soft text-error";
  return (
    <div
      className={`rounded-xl border px-4 py-3 text-sm font-medium ${className}`}
    >
      {message}
    </div>
  );
}

export default SchoolCalendarEventsWorkspace;
