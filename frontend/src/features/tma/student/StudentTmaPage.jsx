import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import DashboardLayout from "../../../components/layout/DashboardLayout";
import { academicService } from "../../../services/academicService";
import { studentTmaService as service } from "../../../services/studentTmaService";
import { tmaReadRequest } from "../../../services/tmaReadRequest";
import { invalidateDashboardSessionCache } from "../../../services/dashboardSessionCache";
import {
  answeredCount,
  savedSelections,
  subjectAssignments,
} from "./attemptState";
import { createAnswerQueue } from "./answerQueue";
import StudentTmaView from "./StudentTmaView";
import "./student-tma.css";

export default function StudentTmaPage() {
  const { subjectResultId, assignmentId } = useParams();
  const [params, setParams] = useSearchParams();
  const resultId = params.get("result");
  const navigate = useNavigate();
  const back = `/student/subjects/${subjectResultId}`;
  const [subject, setSubject] = useState(null);
  const [assignment, setAssignment] = useState(null);
  const [delivery, setDelivery] = useState(null);
  const [result, setResult] = useState(null);
  const [answers, setAnswers] = useState({});
  const [position, setPosition] = useState(0);
  const [saveState, setSaveState] = useState({
    pending: [],
    saving: false,
    error: null,
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState(false);
  const [submissionStarted, setSubmissionStarted] = useState(false);
  const [reload, setReload] = useState(0);
  const queue = useRef(null);
  const live = useRef(null);
  const acting = useRef(false);
  const questionHeading = useRef(null);

  const installAttempt = useCallback((data, generation) => {
    queue.current?.detach();
    setDelivery(data);
    setAnswers(savedSelections(data));
    setPosition(0);
    setSaveState({ pending: [], saving: false, error: null });
    window.dispatchEvent(new Event("weave:tma-attempt-opened"));
    queue.current = createAnswerQueue(
      (questionId, optionId) =>
        service.save(data.attempt.id, questionId, optionId),
      (state) => {
        if (live.current === generation) setSaveState(state);
      },
    );
  }, []);

  useEffect(() => {
    const generation = {};
    live.current = generation;
    setLoading(true);
    setBusy(false);
    setError("");
    setDelivery(null);
    setResult(null);
    setSubmissionStarted(false);
    setConfirmation(false);
    async function load() {
      try {
        const [cards, assignments] = await Promise.all([
          tmaReadRequest((signal) =>
            academicService.listMySubjectCards({ signal }),
          ),
          service.list(),
        ]);
        if (live.current !== generation) return;
        const card = cards.items.find(
          (s) =>
            String(s.id) === subjectResultId ||
            String(s.result_id) === subjectResultId,
        );
        if (!card)
          throw new Error(
            "This subject is no longer available. Return to your subjects.",
          );
        const item = subjectAssignments(assignments, card).find(
          (a) => a.assignment_id === assignmentId,
        );
        setSubject(card);
        setAssignment(item || null);
        if (resultId || item?.attempt_status === "submitted") {
          const id = resultId || item.attempt_id;
          if (!id)
            throw new Error(
              "The server must be updated before this result can be opened.",
            );
          if (item?.attempt_id && item.attempt_id !== id)
            throw new Error(
              "This result does not belong to the selected assignment.",
            );
          const score = await service.result(id);
          if (live.current === generation) setResult(score);
        } else if (!item) {
          throw new Error(
            "This assignment is no longer available. It may have been closed, or your eligibility may have changed.",
          );
        } else if (item.attempt_status === "in_progress" && item.attempt_id) {
          const data = await service.resume(item.attempt_id);
          if (live.current === generation) installAttempt(data, generation);
        }
      } catch (cause) {
        if (live.current === generation)
          setError(cause.message || "Unable to load this assignment.");
      } finally {
        if (live.current === generation) setLoading(false);
      }
    }
    load();
    return () => {
      live.current = null;
      queue.current?.detach();
    };
  }, [assignmentId, subjectResultId, resultId, reload, installAttempt]);

  useEffect(() => {
    const warn = (event) => {
      if (queue.current?.snapshot().pending.length) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    const follow = (event) => {
      if (
        !queue.current?.snapshot().pending.length ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor = event.target.closest?.("a[href]");
      if (
        !anchor ||
        anchor.target === "_blank" ||
        anchor.hasAttribute("download")
      )
        return;
      const destination = new URL(anchor.href, window.location.href);
      if (destination.origin !== window.location.origin) return;
      event.preventDefault();
      event.stopPropagation();
      const generation = live.current;
      queue.current
        .flush()
        .then(() => {
          if (live.current === generation)
            navigate(
              destination.pathname + destination.search + destination.hash,
            );
        })
        .catch((cause) => {
          if (live.current === generation) setError(cause.message);
        });
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", follow, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", follow, true);
    };
  }, [navigate]);

  const act = async (work) => {
    if (acting.current) return;
    const generation = live.current;
    acting.current = true;
    setBusy(true);
    setError("");
    try {
      await work(generation);
    } catch (cause) {
      if (live.current === generation)
        setError(cause.message || "Please check your connection and retry.");
    } finally {
      acting.current = false;
      if (live.current === generation) setBusy(false);
    }
  };
  const start = () =>
    act(async (generation) => {
      const data = await service.start(assignmentId);
      if (live.current === generation) installAttempt(data, generation);
    });
  const leave = () =>
    act(async (generation) => {
      await queue.current?.flush();
      if (live.current === generation) navigate(back);
    });
  const submit = () =>
    act(async (generation) => {
      await queue.current.flush();
      if (live.current !== generation) return;
      setSubmissionStarted(true);
      const score = await service.submit(delivery.attempt.id);
      invalidateDashboardSessionCache();
      if (live.current === generation) {
        setResult(score);
        setConfirmation(false);
        setParams({ result: score.attempt_id }, { replace: true });
      }
    });
  const questions = delivery?.questions || [];
  const current = questions[position];
  const answered = answeredCount(questions, answers);
  const component = subject?.components?.find(
    (c) => c.assessment_component_id === assignment?.assessment_component_id,
  );
  const title =
    result && !assignment
      ? "Tutor Marked Assignment"
      : subject?.subject_name || "Tutor Marked Assignment";
  const choose = (questionId, optionId) => {
    if (busy || confirmation || submissionStarted) return;
    setAnswers((old) => ({ ...old, [questionId]: optionId }));
    queue.current.select(questionId, optionId);
  };
  const go = (next) => {
    if (busy || submissionStarted) return;
    setPosition(next);
    questionHeading.current?.scrollIntoView({
      block: "start",
      behavior: "instant",
    });
    questionHeading.current?.focus({ preventScroll: true });
  };

  return (
    <DashboardLayout
      role="student"
      title={delivery && !result ? undefined : title}
      description={delivery && !result ? undefined : "Tutor Marked Assignment"}
    >
      <StudentTmaView
        {...{
          back,
          error,
          delivery,
          result,
          saveState,
          loading,
          subject,
          assignment,
          component,
          questions,
          current,
          answered,
          answers,
          position,
          busy,
          confirmation,
          submissionStarted,
          questionHeading,
          leave,
          start,
          submit,
          choose,
          go,
          setConfirmation,
          setReload,
        }}
        onRetrySave={() => act(() => queue.current.flush())}
      />
    </DashboardLayout>
  );
}
