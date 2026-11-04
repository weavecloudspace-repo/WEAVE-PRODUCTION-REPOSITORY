import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  MessageCircle,
  Plus,
  Search,
  Send,
  Volume2,
  VolumeX,
  Wifi,
  WifiOff,
} from "lucide-react";

import DashboardLayout from "../../components/layout/DashboardLayout";
import Button from "../../components/ui/Button";
import EmptyState from "../../components/shared/EmptyState";
import LoadingState from "../../components/shared/LoadingState";
import { authSession, getErrorMessage } from "../../services/api";
import {
  MESSAGE_REALTIME_EVENTS,
  emitNotificationsChanged,
  messageService,
} from "../../services/communicationService";
import { realtimeClient } from "../../services/realtimeClient";
import {
  getMessageSoundEnabled,
  playIncomingMessageSound,
  primeMessageSound,
  setMessageSoundEnabled,
} from "../../utils/messageSound";

const [MESSAGE_CREATED_EVENT, MESSAGE_READ_EVENT] = MESSAGE_REALTIME_EVENTS;
const CONVERSATION_PAGE_SIZE = 30;
const MAX_SEEN_REALTIME_EVENTS = 300;

const actorTypeLabels = {
  superadmin: "WEAVE administration",
  tenant_admin: "Administrators",
  teacher: "Teachers",
  student: "Students",
  parent: "Parents",
};

const authRoleToActorType = {
  admin: "tenant_admin",
  superadmin: "superadmin",
  teacher: "teacher",
  student: "student",
  parent: "parent",
};

const roleLabel = (actorType) =>
  actorTypeLabels[actorType] ||
  String(actorType || "contact").replaceAll("_", " ");
const actorKeyFor = (item) => `${item?.actor_type}:${item?.actor_id}`;
const shortActorId = (value) => (value ? String(value).slice(0, 8) : "unknown");

const decodeTokenPayload = (token) => {
  try {
    const payload = token?.split(".")?.[1];
    if (!payload) return {};
    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padding = "=".repeat((4 - (normalizedPayload.length % 4)) % 4);
    return JSON.parse(atob(`${normalizedPayload}${padding}`));
  } catch {
    return {};
  }
};

const flattenRecipients = (groups) =>
  (groups || []).flatMap((group) =>
    (group.recipients || []).map((recipient) => ({
      ...recipient,
      group_label: recipient.group_label || group.label,
    })),
  );

const identityLabel = (
  identity,
  currentActorKey,
  { useSelfLabel = true } = {},
) => {
  if (!identity) return "Unknown contact";
  if (useSelfLabel && actorKeyFor(identity) === currentActorKey) return "You";
  return (
    identity.label ||
    `${roleLabel(identity.actor_type)} ${shortActorId(identity.actor_id)}`
  );
};

const currentUserLabel = (user, actorType, actorId) => {
  if (actorType === "student") {
    return (
      user.admission_number ||
      user.student_number ||
      user.email ||
      shortActorId(actorId)
    );
  }
  if (actorType === "teacher") {
    return user.staff_id || user.email || shortActorId(actorId);
  }
  return user.email || shortActorId(actorId);
};

const initialsFor = (label) => {
  const parts = String(label || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts.at(-1)[0]}`.toUpperCase();
};

const counterpartFor = (conversation, currentActorKey, directory) => {
  const other = (conversation?.participants || []).find(
    (participant) => actorKeyFor(participant) !== currentActorKey,
  );
  return other ? directory[actorKeyFor(other)] || other : null;
};

const conversationTitle = (conversation, currentActorKey, directory) => {
  if (conversation?.subject) return conversation.subject;
  return identityLabel(
    counterpartFor(conversation, currentActorKey, directory),
    currentActorKey,
    { useSelfLabel: false },
  );
};

const timestampLabel = (value) => {
  if (!value) return "";
  const date = new Date(value);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  }
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
};

const fullTimestampLabel = (value) => {
  if (!value) return "";
  return new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
};

const dayLabel = (value) => {
  if (!value) return "";
  const date = new Date(value);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
};

const realtimeMessageFrom = (data) => ({
  id: data.message_id,
  conversation_id: data.conversation_id,
  sender_actor_type: data.sender_actor_type,
  sender_actor_id: data.sender_actor_id,
  body: data.body || "",
  created_at: data.created_at || new Date().toISOString(),
  deleted_at: null,
});

const appendUniqueMessage = (messages, message) => {
  const current = messages || [];
  if (!message?.id) return current;
  if (current.some((item) => String(item.id) === String(message.id))) {
    return current;
  }
  return [...current, message];
};

function Avatar({ label, size = "md" }) {
  const sizeClass =
    size === "sm" ? "h-9 w-9 text-[11px]" : "h-11 w-11 text-xs";
  return (
    <span
      className={`flex shrink-0 items-center justify-center rounded-full border border-primary/15 bg-primary-soft font-black tracking-wide text-primary ${sizeClass}`}
      aria-hidden="true"
    >
      {initialsFor(label)}
    </span>
  );
}

export default function MessagesPage() {
  const [searchParams] = useSearchParams();
  const requestedConversationId = searchParams.get("conversation") || "";

  const [conversations, setConversations] = useState([]);
  const [conversationTotal, setConversationTotal] = useState(0);
  const [conversationPage, setConversationPage] = useState(1);
  const [selectedId, setSelectedId] = useState(requestedConversationId);
  const [mobileChatOpen, setMobileChatOpen] = useState(Boolean(requestedConversationId));
  const [selected, setSelected] = useState(null);
  const [recipientGroups, setRecipientGroups] = useState([]);
  const [recipientKey, setRecipientKey] = useState("");
  const [sidebarMode, setSidebarMode] = useState("chats");
  const [sidebarRole, setSidebarRole] = useState("all");
  const [sidebarSearch, setSidebarSearch] = useState("");
  const [appliedSidebarSearch, setAppliedSidebarSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedSidebarSearch(sidebarSearch.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [sidebarSearch]);
  useEffect(() => {
    setConversationPage(1);
  }, [appliedSidebarSearch, sidebarRole]);
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sendError, setSendError] = useState("");
  const [liveMessageId, setLiveMessageId] = useState("");
  const [liveConversationId, setLiveConversationId] = useState("");
  const [soundEnabled, setSoundEnabled] = useState(() =>
    getMessageSoundEnabled(),
  );
  const [connectionStatus, setConnectionStatus] = useState(() =>
    realtimeClient.ready ? "ready" : "connecting",
  );

  const threadEndRef = useRef(null);
  const mobileBackRef = useRef(null);
  const mobileCardRef = useRef(null);
  const selectedIdRef = useRef(selectedId);
  const recipientKeyRef = useRef(recipientKey);
  const seenRealtimeEventsRef = useRef(new Set());
  const liveAnimationTimerRef = useRef(null);

  const currentUser = useMemo(() => authSession.getUser() || {}, []);
  const tokenPayload = useMemo(
    () => decodeTokenPayload(authSession.getToken?.()),
    [],
  );
  const currentActorType =
    currentUser.actor_type ||
    tokenPayload.actor_type ||
    authRoleToActorType[String(currentUser.role || "").toLowerCase()] ||
    String(currentUser.role || "").toLowerCase();
  const currentActorId =
    currentUser.membership_id ||
    currentUser.actor_id ||
    tokenPayload.sub ||
    currentUser.id;
  const currentActorKey = `${currentActorType}:${currentActorId}`;
  const dashboardRole = String(currentUser.role || "admin").toLowerCase();

  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    recipientKeyRef.current = recipientKey;
  }, [recipientKey]);

  useEffect(() => {
    if (!window.matchMedia("(max-width: 1023px)").matches) return;
    const frame = window.requestAnimationFrame(() => {
      const target = mobileChatOpen ? mobileBackRef.current : mobileCardRef.current;
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: "nearest" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [mobileChatOpen]);

  useEffect(() => {
    if (requestedConversationId) {
      setMobileChatOpen(true);
      setSelectedId(requestedConversationId);
      setRecipientKey("");
      setSidebarMode("chats");
    }
  }, [requestedConversationId]);

  const recipients = useMemo(
    () => flattenRecipients(recipientGroups),
    [recipientGroups],
  );

  const identityDirectory = useMemo(() => {
    const rows = {};
    recipients.forEach((recipient) => {
      rows[actorKeyFor(recipient)] = recipient;
    });
    [...conversations, selected]
      .filter(Boolean)
      .forEach((conversation) => {
        (conversation.participants || []).forEach((participant) => {
          const key = actorKeyFor(participant);
          if (!rows[key]) rows[key] = participant;
        });
      });
    if (!rows[currentActorKey]) {
      rows[currentActorKey] = {
        actor_type: currentActorType,
        actor_id: currentActorId,
        label: currentUserLabel(
          currentUser,
          currentActorType,
          currentActorId,
        ),
        group_label: roleLabel(currentActorType),
      };
    }
    return rows;
  }, [
    conversations,
    currentActorId,
    currentActorKey,
    currentActorType,
    currentUser,
    recipients,
    selected,
  ]);

  const recipientRoleOptions = useMemo(
    () => [
      ...new Set(
        recipients.map((recipient) => recipient.actor_type).filter(Boolean),
      ),
    ],
    [recipients],
  );

  const selectedRecipient = useMemo(
    () =>
      recipients.find((recipient) => actorKeyFor(recipient) === recipientKey),
    [recipientKey, recipients],
  );

  const conversationPageCount = Math.max(
    1,
    Math.ceil(conversationTotal / CONVERSATION_PAGE_SIZE),
  );

  // Conversation list is filtered on the server before pagination.
  const filteredConversations = conversations;

  const filteredRecipientGroups = useMemo(() => {
    const query = sidebarSearch.trim().toLowerCase();
    return (recipientGroups || [])
      .map((group) => ({
        ...group,
        recipients: (group.recipients || []).filter((recipient) => {
          if (sidebarRole !== "all" && recipient.actor_type !== sidebarRole) {
            return false;
          }
          if (!query) return true;
          return `${recipient.label} ${recipient.group_label || group.label} ${recipient.actor_id}`
            .toLowerCase()
            .includes(query);
        }),
      }))
      .filter((group) => group.recipients.length > 0);
  }, [recipientGroups, sidebarRole, sidebarSearch]);

  const refreshConversations = useCallback(
    async ({ showLoading = false } = {}) => {
      if (showLoading) setLoading(true);
      try {
        const skip = (conversationPage - 1) * CONVERSATION_PAGE_SIZE;
        const response = await messageService.listConversations({
          skip,
          limit: CONVERSATION_PAGE_SIZE,
          search: appliedSidebarSearch || undefined,
          counterpart_type: sidebarRole === "all" ? undefined : sidebarRole,
        });
        const rows = response?.items || [];
        setConversations(rows);
        setConversationTotal(Number(response?.total || rows.length));
        if (
          !selectedIdRef.current &&
          !recipientKeyRef.current &&
          rows[0]?.id
        ) {
          setSelectedId(rows[0].id);
        }
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [conversationPage, appliedSidebarSearch, sidebarRole],
  );

  const refreshRecipients = useCallback(async () => {
    const response = await messageService.availableRecipients();
    setRecipientGroups(response?.groups || []);
  }, []);

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      await Promise.all([refreshConversations(), refreshRecipients()]);
    } catch (err) {
      setError(getErrorMessage(err, "Could not load messages."));
    } finally {
      setLoading(false);
    }
  }, [refreshConversations, refreshRecipients]);

  useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return undefined;
    }

    let mounted = true;
    setSendError("");
    messageService
      .markRead(selectedId)
      .then((response) => {
        if (!mounted) return;
        setSelected(response);
        setRecipientKey("");
        emitNotificationsChanged();
        setConversations((current) =>
          current.map((conversation) =>
            conversation.id === response.id
              ? { ...conversation, ...response, unread_count: 0 }
              : conversation,
          ),
        );
      })
      .catch((err) => {
        if (mounted) {
          setError(getErrorMessage(err, "Could not open conversation."));
        }
      });

    return () => {
      mounted = false;
    };
  }, [selectedId]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      threadEndRef.current?.scrollIntoView({ block: "end" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [selected?.id, selected?.messages?.length]);

  useEffect(() => {
    const prime = () => {
      if (soundEnabled) void primeMessageSound();
    };
    window.addEventListener("pointerdown", prime, { once: true });
    window.addEventListener("keydown", prime, { once: true });
    return () => {
      window.removeEventListener("pointerdown", prime);
      window.removeEventListener("keydown", prime);
    };
  }, [soundEnabled]);

  useEffect(() => {
    const markEventSeen = (eventId) => {
      if (!eventId) return false;
      const seen = seenRealtimeEventsRef.current;
      if (seen.has(eventId)) return true;
      seen.add(eventId);
      if (seen.size > MAX_SEEN_REALTIME_EVENTS) {
        seen.delete(seen.values().next().value);
      }
      return false;
    };

    const animateLiveMessage = (conversationId, messageId) => {
      setLiveConversationId(conversationId || "");
      setLiveMessageId(messageId || "");
      if (liveAnimationTimerRef.current) {
        window.clearTimeout(liveAnimationTimerRef.current);
      }
      liveAnimationTimerRef.current = window.setTimeout(() => {
        setLiveConversationId("");
        setLiveMessageId("");
      }, 850);
    };

    const onMessageCreated = async (event) => {
      if (markEventSeen(event?.event_id)) return;
      const data = event?.data || {};
      if (!data.conversation_id || !data.message_id) return;

      const senderKey = `${data.sender_actor_type}:${data.sender_actor_id}`;
      const incoming = senderKey !== currentActorKey;
      const message = realtimeMessageFrom(data);
      const activeConversation =
        String(selectedIdRef.current || "") === String(data.conversation_id);

      animateLiveMessage(data.conversation_id, data.message_id);

      setConversations((current) =>
        [...current]
          .map((conversation) => {
            if (String(conversation.id) !== String(data.conversation_id)) {
              return conversation;
            }
            return {
              ...conversation,
              updated_at: message.created_at,
              messages: appendUniqueMessage(conversation.messages, message),
              unread_count:
                incoming && !activeConversation
                  ? Number(conversation.unread_count || 0) + 1
                  : activeConversation
                    ? 0
                    : Number(conversation.unread_count || 0),
            };
          })
          .sort(
            (a, b) =>
              new Date(b.updated_at || b.messages?.at(-1)?.created_at || 0) -
              new Date(a.updated_at || a.messages?.at(-1)?.created_at || 0),
          ),
      );

      if (activeConversation) {
        setSelected((current) =>
          current && String(current.id) === String(data.conversation_id)
            ? {
                ...current,
                updated_at: message.created_at,
                messages: appendUniqueMessage(current.messages, message),
                unread_count: 0,
              }
            : current,
        );
        if (incoming) {
          void messageService
            .markRead(data.conversation_id)
            .then((response) => {
              if (
                String(selectedIdRef.current || "") ===
                String(data.conversation_id)
              ) {
                setSelected(response);
              }
              emitNotificationsChanged();
            })
            .catch(() => undefined);
        }
      } else {
        void refreshConversations().catch(() => undefined);
      }

      if (incoming) {
        void playIncomingMessageSound({ enabled: soundEnabled });
      }
      emitNotificationsChanged();
    };

    const onMessageRead = async (event) => {
      if (markEventSeen(event?.event_id)) return;
      const conversationId = event?.data?.conversation_id;
      if (!conversationId) return;
      if (String(selectedIdRef.current || "") === String(conversationId)) {
        try {
          const response = await messageService.getConversation(conversationId);
          if (
            String(selectedIdRef.current || "") === String(conversationId)
          ) {
            setSelected(response);
          }
        } catch {
          // Reconnect reconciliation is the fallback for an ephemeral read receipt.
        }
      }
    };

    const unsubscribers = [
      realtimeClient.subscribe(MESSAGE_CREATED_EVENT, onMessageCreated),
      realtimeClient.subscribe(MESSAGE_READ_EVENT, onMessageRead),
      realtimeClient.subscribeConnection((state) => {
        setConnectionStatus(state.status);
        if (state.status === "reconnected") {
          void Promise.all([
            refreshConversations(),
            refreshRecipients(),
            selectedIdRef.current
              ? messageService
                  .getConversation(selectedIdRef.current)
                  .then(setSelected)
              : Promise.resolve(),
          ]).catch(() => undefined);
        }
      }),
    ];

    return () => {
      unsubscribers.forEach((unsubscribe) => unsubscribe());
      if (liveAnimationTimerRef.current) {
        window.clearTimeout(liveAnimationTimerRef.current);
      }
    };
  }, [currentActorKey, refreshConversations, refreshRecipients, soundEnabled]);

  const startNewChat = () => {
    setMobileChatOpen(false);
    setSidebarMode("people");
    setSidebarSearch("");
    setSidebarRole("all");
  };

  const chooseRecipient = (recipient) => {
    setMobileChatOpen(true);
    setRecipientKey(actorKeyFor(recipient));
    setSelectedId("");
    setSelected(null);
    setBody("");
    setSendError("");
  };

  const chooseConversation = (conversationId) => {
    setMobileChatOpen(true);
    setRecipientKey("");
    setSelectedId(conversationId);
    setSidebarMode("chats");
    setSendError("");
  };

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    setMessageSoundEnabled(next);
    if (next) void primeMessageSound();
  };

  const sendMessage = async (event) => {
    event.preventDefault();
    setSendError("");
    const text = body.trim();
    if (!text) return;
    if (!selected?.id && !selectedRecipient) {
      setSendError("Choose a permitted recipient first.");
      return;
    }
    if (selected?.id && selected.can_reply === false) {
      setSendError(
        selected.read_only_reason || "This conversation is read-only.",
      );
      return;
    }

    setSending(true);
    try {
      if (selected?.id) {
        const created = await messageService.sendMessage(selected.id, {
          body: text,
        });
        setSelected((current) =>
          current
            ? {
                ...current,
                updated_at: created.created_at,
                messages: appendUniqueMessage(current.messages, created),
              }
            : current,
        );
        setConversations((current) =>
          current.map((conversation) =>
            conversation.id === selected.id
              ? {
                  ...conversation,
                  updated_at: created.created_at,
                  messages: appendUniqueMessage(
                    conversation.messages,
                    created,
                  ),
                }
              : conversation,
          ),
        );
      } else {
        const conversation = await messageService.createConversation({
          recipient: {
            actor_type: selectedRecipient.actor_type,
            actor_id: selectedRecipient.actor_id,
          },
          body: text,
        });
        const alreadyExists = conversations.some(
          (item) => item.id === conversation.id,
        );
        setConversationPage(1);
        setSidebarMode("chats");
        setRecipientKey("");
        setSelectedId(conversation.id);
        setSelected(conversation);
        setConversations((current) => [
          conversation,
          ...current.filter((item) => item.id !== conversation.id),
        ]);
        if (!alreadyExists) {
          setConversationTotal((current) => current + 1);
        }
      }
      setBody("");
    } catch (err) {
      setSendError(getErrorMessage(err, "Could not send message."));
    } finally {
      setSending(false);
    }
  };

  const handleComposerKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sending && body.trim()) {
        event.currentTarget.form?.requestSubmit();
      }
    }
  };

  const selectedCounterpart = selected
    ? counterpartFor(selected, currentActorKey, identityDirectory)
    : selectedRecipient;
  const selectedTitle = selected
    ? conversationTitle(selected, currentActorKey, identityDirectory)
    : selectedRecipient?.label || "Messages";
  const selectedMeta = selectedCounterpart
    ? selectedCounterpart.group_label || roleLabel(selectedCounterpart.actor_type)
    : "Choose a permitted person from the directory";
  const liveConnected = ["ready", "reconnected"].includes(connectionStatus);

  const otherParticipant = selected
    ? (selected.participants || []).find(
        (participant) => actorKeyFor(participant) !== currentActorKey,
      )
    : null;
  const lastReadMessageId = otherParticipant?.last_read_message_id;
  const selectedMessages = selected?.messages || [];
  const lastReadIndex = selectedMessages.findIndex(
    (message) => String(message.id) === String(lastReadMessageId || ""),
  );

  return (
    <DashboardLayout role={dashboardRole}>
      <section data-mobile-chat-open={String(mobileChatOpen)} className="weave-chat-shell grid h-[calc(100dvh-6.5rem)] min-h-[36rem] w-full grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-hidden lg:h-[calc(100dvh-8rem)] lg:grid-cols-[21rem_minmax(0,1fr)] lg:grid-rows-1 lg:gap-4 xl:grid-cols-[23.5rem_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
          <div className="border-b border-border p-3 sm:p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h1 className="text-lg font-black tracking-tight text-text">
                  Messages
                </h1>
                <p className="mt-0.5 text-xs text-text-muted">
                  Direct conversations only
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={startNewChat}
                aria-label="Start new conversation"
              >
                <Plus className="h-4 w-4" />
                New
              </Button>
            </div>

            <div className="mt-4 grid grid-cols-2 rounded-xl bg-surface-muted p-1">
              <button
                type="button"
                onClick={() => {
                  setSidebarMode("chats");
                  setSidebarSearch("");
                  setSidebarRole("all");
                }}
                className={`rounded-lg px-3 py-2 text-xs font-bold transition ${sidebarMode === "chats" ? "bg-surface text-text shadow-sm" : "text-text-muted hover:text-text"}`}
              >
                Chats
              </button>
              <button
                type="button"
                onClick={() => {
                  setSidebarMode("people");
                  setSidebarSearch("");
                  setSidebarRole("all");
                }}
                className={`rounded-lg px-3 py-2 text-xs font-bold transition ${sidebarMode === "people" ? "bg-surface text-text shadow-sm" : "text-text-muted hover:text-text"}`}
              >
                People
              </button>
            </div>

            <div className="relative mt-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-faint" />
              <input
                className="input-base h-10 pl-9 text-sm"
                value={sidebarSearch}
                onChange={(event) => setSidebarSearch(event.target.value)}
                placeholder={
                  sidebarMode === "people"
                    ? "Search permitted people"
                    : "Search conversations"
                }
                aria-label="Search messages"
              />
            </div>

            <div className="mt-3 flex gap-1.5 overflow-x-auto pb-1">
              <button
                type="button"
                onClick={() => setSidebarRole("all")}
                className={`weave-message-role-filter rounded-full px-2.5 py-1 text-[11px] font-bold transition ${sidebarRole === "all" ? "bg-primary text-primary-foreground" : "bg-surface-muted text-text-muted hover:text-text"}`}
              >
                All
              </button>
              {recipientRoleOptions.map((actorType) => (
                <button
                  key={actorType}
                  type="button"
                  onClick={() => setSidebarRole(actorType)}
                  className={`weave-message-role-filter rounded-full px-2.5 py-1 text-[11px] font-bold transition ${sidebarRole === actorType ? "bg-primary text-primary-foreground" : "bg-surface-muted text-text-muted hover:text-text"}`}
                >
                  {roleLabel(actorType)}
                </button>
              ))}
            </div>
          </div>

          {error ? (
            <div role="alert" className="border-b border-error/30 bg-error-soft px-4 py-3 text-sm font-semibold text-error lg:hidden">
              {error}
            </div>
          ) : null}

          <div className="weave-chat-directory min-h-0 flex-1 overflow-y-auto">
            {loading ? <LoadingState label="Loading messages" /> : null}

            {!loading && sidebarMode === "chats" ? (
              filteredConversations.length ? (
                <div className="divide-y divide-border">
                  {filteredConversations.map((conversation) => {
                    const counterpart = counterpartFor(
                      conversation,
                      currentActorKey,
                      identityDirectory,
                    );
                    const title = conversationTitle(
                      conversation,
                      currentActorKey,
                      identityDirectory,
                    );
                    const latest = conversation.messages?.at(-1);
                    const latestMine = latest
                      ? `${latest.sender_actor_type}:${latest.sender_actor_id}` ===
                        currentActorKey
                      : false;
                    const active = selectedId === conversation.id;
                    const live = liveConversationId === conversation.id;
                    return (
                      <button
                        key={conversation.id}
                        type="button"
                        onClick={(event) => {
                          mobileCardRef.current = event.currentTarget;
                          chooseConversation(conversation.id);
                        }}
                        className={`block w-full px-3 py-3 text-left transition sm:px-4 ${active ? "bg-primary-soft/70" : "hover:bg-surface-muted/50"} ${live ? "weave-conversation-live" : ""}`}
                      >
                        <span className="flex items-start gap-3">
                          <Avatar label={title} size="sm" />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center justify-between gap-2">
                              <span className="truncate text-sm font-bold text-text">
                                {title}
                              </span>
                              <span className="shrink-0 text-[10px] font-semibold text-text-faint">
                                {timestampLabel(
                                  latest?.created_at || conversation.updated_at,
                                )}
                              </span>
                            </span>
                            <span className="mt-0.5 block truncate text-[11px] font-semibold text-text-faint">
                              {counterpart?.group_label ||
                                roleLabel(counterpart?.actor_type)}
                            </span>
                            <span className="mt-1 flex items-center gap-2">
                              <span
                                className={`min-w-0 flex-1 truncate text-xs ${conversation.unread_count ? "font-bold text-text" : "text-text-muted"}`}
                              >
                                {latestMine ? "You: " : ""}
                                {latest?.body || "No messages yet"}
                              </span>
                              {conversation.unread_count ? (
                                <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary px-1.5 text-[10px] font-black text-primary-foreground">
                                  {conversation.unread_count}
                                </span>
                              ) : null}
                            </span>
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="p-4">
                  <EmptyState
                    icon={MessageCircle}
                    title="No matching chats"
                    description="Start a new conversation with someone you are allowed to message."
                  />
                </div>
              )
            ) : null}

            {!loading && sidebarMode === "people" ? (
              filteredRecipientGroups.length ? (
                <div className="pb-3">
                  {filteredRecipientGroups.map((group) => (
                    <div key={group.label}>
                      <div className="sticky top-0 z-10 border-y border-border bg-surface-muted/95 px-4 py-2 backdrop-blur">
                        <p className="text-[10px] font-black uppercase tracking-[0.12em] text-text-faint">
                          {group.label}
                        </p>
                      </div>
                      {group.recipients.map((recipient) => {
                        const selectedPerson =
                          actorKeyFor(recipient) === recipientKey;
                        return (
                          <button
                            key={actorKeyFor(recipient)}
                            type="button"
                            onClick={(event) => {
                              mobileCardRef.current = event.currentTarget;
                              chooseRecipient(recipient);
                            }}
                            className={`flex w-full items-center gap-3 px-4 py-3 text-left transition ${selectedPerson ? "bg-primary-soft/70" : "hover:bg-surface-muted/50"}`}
                          >
                            <Avatar label={recipient.label} size="sm" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-bold text-text">
                                {recipient.label}
                              </span>
                              <span className="mt-0.5 block truncate text-xs text-text-muted">
                                {recipient.group_label ||
                                  roleLabel(recipient.actor_type)}
                              </span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-4">
                  <EmptyState
                    icon={Search}
                    title="No permitted people found"
                    description="Your messaging directory only shows recipients allowed by the current school hierarchy."
                  />
                </div>
              )
            ) : null}
          </div>

          {sidebarMode === "chats" ? (
            <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2 text-[11px] font-semibold text-text-muted sm:px-4">
              <span>
                Page {conversationPage} of {conversationPageCount}
              </span>
              <div className="flex gap-1.5">
                <Button
                  type="button"
                  size="xs"
                  variant="ghost"
                  disabled={loading || conversationPage <= 1}
                  onClick={() =>
                    setConversationPage((current) => Math.max(1, current - 1))
                  }
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  size="xs"
                  variant="ghost"
                  disabled={loading || conversationPage >= conversationPageCount}
                  onClick={() =>
                    setConversationPage((current) =>
                      Math.min(conversationPageCount, current + 1),
                    )
                  }
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </aside>

        <main className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
          {error ? (
            <div className="border-b border-error/30 bg-error-soft px-4 py-3 text-sm font-semibold text-error">
              {error}
            </div>
          ) : null}

          <header className="weave-chat-header flex min-h-[4.75rem] shrink-0 items-center justify-between gap-3 border-b border-border px-3 py-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-3">
              <Button
                ref={mobileBackRef}
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 lg:hidden"
                aria-label="Back to conversations and people"
                onClick={() => setMobileChatOpen(false)}
              >
                <ArrowLeft className="h-5 w-5" />
              </Button>
              <Avatar label={selectedTitle} />
              <div className="min-w-0">
                <h2 className="truncate text-sm font-black text-text sm:text-base">
                  {selectedTitle}
                </h2>
                <p className="mt-0.5 truncate text-xs text-text-muted">
                  {selectedMeta}
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <span
                className={`hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold sm:flex ${liveConnected ? "border-primary/20 bg-primary-soft text-primary" : "border-border bg-surface-muted text-text-muted"}`}
                title={
                  liveConnected
                    ? "Realtime WebSocket connected"
                    : "Realtime connection is reconnecting"
                }
              >
                {liveConnected ? (
                  <Wifi className="h-3.5 w-3.5" />
                ) : (
                  <WifiOff className="h-3.5 w-3.5" />
                )}
                {liveConnected ? "Live" : "Reconnecting"}
              </span>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={
                  soundEnabled
                    ? "Mute incoming message sound"
                    : "Enable incoming message sound"
                }
                title={
                  soundEnabled
                    ? "Incoming message sound on"
                    : "Incoming message sound off"
                }
                onClick={toggleSound}
              >
                {soundEnabled ? (
                  <Volume2 className="h-4 w-4" />
                ) : (
                  <VolumeX className="h-4 w-4" />
                )}
              </Button>
            </div>
          </header>

          {!selected && !selectedRecipient ? (
            <div className="flex min-h-0 flex-1 items-center justify-center bg-surface-muted/15 p-6">
              <div className="max-w-md text-center">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/15 bg-primary-soft text-primary shadow-sm">
                  <MessageCircle className="h-6 w-6" />
                </span>
                <h3 className="mt-4 text-lg font-black text-text">
                  Pick a conversation or start a new one
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-text-muted">
                  The people list is generated from your current school role and
                  academic relationships, so only permitted contacts appear.
                </p>
                <Button className="mt-4" type="button" onClick={startNewChat}>
                  <Plus className="h-4 w-4" /> Start new chat
                </Button>
              </div>
            </div>
          ) : (
            <>
              <div className="weave-chat-thread min-h-0 flex-1 overflow-y-auto bg-surface-muted/15 px-3 py-4 sm:px-5 sm:py-5">
                {!selected ? (
                  <div className="flex h-full min-h-[16rem] items-center justify-center">
                    <div className="max-w-sm text-center">
                      <div className="flex justify-center">
                        <Avatar label={selectedRecipient?.label} />
                      </div>
                      <h3 className="mt-3 font-black text-text">
                        Start a conversation with {selectedRecipient?.label}
                      </h3>
                      <p className="mt-1 text-sm text-text-muted">
                        {selectedRecipient?.group_label ||
                          roleLabel(selectedRecipient?.actor_type)}
                      </p>
                    </div>
                  </div>
                ) : selectedMessages.length ? (
                  selectedMessages.map((message, index) => {
                    const mine =
                      `${message.sender_actor_type}:${message.sender_actor_id}` ===
                      currentActorKey;
                    const sender =
                      identityDirectory[
                        `${message.sender_actor_type}:${message.sender_actor_id}`
                      ] || {
                        actor_type: message.sender_actor_type,
                        actor_id: message.sender_actor_id,
                      };
                    const previous = selectedMessages[index - 1];
                    const showDay =
                      !previous ||
                      new Date(previous.created_at).toDateString() !==
                        new Date(message.created_at).toDateString();
                    const read = mine && lastReadIndex >= index;
                    const isLastMine =
                      mine &&
                      !selectedMessages
                        .slice(index + 1)
                        .some(
                          (item) =>
                            `${item.sender_actor_type}:${item.sender_actor_id}` ===
                            currentActorKey,
                        );
                    return (
                      <div key={message.id}>
                        {showDay ? (
                          <div
                            className="my-4 flex items-center gap-3"
                            aria-hidden="true"
                          >
                            <span className="h-px flex-1 bg-border" />
                            <span className="rounded-full border border-border bg-surface px-2.5 py-1 text-[10px] font-bold text-text-faint shadow-sm">
                              {dayLabel(message.created_at)}
                            </span>
                            <span className="h-px flex-1 bg-border" />
                          </div>
                        ) : null}
                        <article
                          className={`mb-2.5 flex ${mine ? "justify-end" : "justify-start"}`}
                        >
                          <div
                            data-mine={String(mine)}
                            data-live={String(
                              String(liveMessageId) === String(message.id),
                            )}
                            className={`weave-message-bubble max-w-[86%] rounded-[1.15rem] px-3.5 py-2.5 shadow-sm sm:max-w-[72%] sm:px-4 ${mine ? "rounded-br-[0.35rem] bg-primary text-primary-foreground" : "rounded-bl-[0.35rem] border border-border bg-surface text-text"}`}
                          >
                            {!mine ? (
                              <p className="mb-1 text-[10px] font-black uppercase tracking-wide text-text-faint">
                                {identityLabel(sender, currentActorKey, {
                                  useSelfLabel: false,
                                })}
                              </p>
                            ) : null}
                            <p className="weave-message-body whitespace-pre-wrap break-words text-sm leading-relaxed">
                              {message.body}
                            </p>
                            <div
                              className={`weave-message-meta mt-1.5 flex flex-wrap items-center justify-end gap-1 text-xs ${mine ? "text-primary-foreground" : "text-text-muted"}`}
                            >
                              <time>{fullTimestampLabel(message.created_at)}</time>
                              {mine && isLastMine ? (
                                read ? (
                                  <span
                                    className="flex items-center gap-0.5"
                                    title="Read"
                                  >
                                    <CheckCheck className="h-3.5 w-3.5" />
                                    <span className="sr-only">Read</span>
                                  </span>
                                ) : (
                                  <span
                                    className="flex items-center gap-0.5"
                                    title="Sent"
                                  >
                                    <Check className="h-3.5 w-3.5" />
                                    <span className="sr-only">Sent</span>
                                  </span>
                                )
                              ) : null}
                            </div>
                          </div>
                        </article>
                      </div>
                    );
                  })
                ) : (
                  <div className="flex h-full items-center justify-center">
                    <EmptyState
                      icon={MessageCircle}
                      title="No messages in this conversation yet"
                    />
                  </div>
                )}
                <div ref={threadEndRef} />
              </div>

              <form
                onSubmit={sendMessage}
                className="weave-chat-composer shrink-0 border-t border-border bg-surface px-3 py-3 sm:px-4"
              >
                {selected?.can_reply === false ? (
                  <div className="rounded-xl border border-border bg-surface-muted px-3 py-2.5 text-xs font-semibold text-text-muted">
                    {selected.read_only_reason ||
                      "This conversation is read-only because the current school relationship no longer permits replies."}
                  </div>
                ) : (
                  <>
                    {sendError ? (
                      <p className="mb-2 text-xs font-semibold text-error">
                        {sendError}
                      </p>
                    ) : null}
                    <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface-muted/35 p-1.5 focus-within:border-primary/45 focus-within:ring-2 focus-within:ring-primary/10">
                      <textarea
                        rows={1}
                        className="min-h-10 flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm leading-relaxed text-text outline-none placeholder:text-text-faint"
                        value={body}
                        onChange={(event) => setBody(event.target.value)}
                        onKeyDown={handleComposerKeyDown}
                        placeholder={
                          selected
                            ? `Message ${selectedTitle}`
                            : `Message ${selectedRecipient?.label || "recipient"}`
                        }
                        aria-label="Message"
                      />
                      <Button
                        type="submit"
                        size="icon"
                        aria-label="Send message"
                        disabled={sending || !body.trim()}
                      >
                        <Send className="h-4 w-4" />
                      </Button>
                    </div>
                    <div className="weave-chat-composer-help mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1 text-xs leading-5 text-text-muted">
                      <span>Enter to send · Shift + Enter for a new line</span>
                      <span>
                        {liveConnected
                          ? "Realtime connected"
                          : "Sending still works while realtime reconnects"}
                      </span>
                    </div>
                  </>
                )}
              </form>
            </>
          )}
        </main>
      </section>
    </DashboardLayout>
  );
}
