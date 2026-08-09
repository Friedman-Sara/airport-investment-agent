(() => {
  const messagesEl = document.getElementById("messages");
  const form = document.getElementById("chat-form");
  const questionEl = document.getElementById("question");
  const sendBtn = document.getElementById("send");
  const newChatBtn = document.getElementById("new-chat");

  let threadId = localStorage.getItem("airport_agent_thread_id") || null;
  let busy = false;

  function escapeHtml(text) {
    return text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatAnswer(text) {
    const escaped = escapeHtml(text);
    const withCode = escaped.replace(/`([^`]+)`/g, "<code>$1</code>");
    return withCode
      .split(/\n{2,}/)
      .map((block) => `<p>${block.replaceAll("\n", "<br>")}</p>`)
      .join("");
  }

  function appendMessage(role, content, options = {}) {
    const article = document.createElement("article");
    article.className = `message ${role}`;
    if (options.error) article.classList.add("error");
    if (options.pending) article.classList.add("pending");

    const roleLabel = role === "user" ? "You" : "Agent";
    article.innerHTML = `
      <div class="meta">
        <span class="role">${roleLabel}</span>
        ${options.tag ? `<span class="tag">${options.tag}</span>` : ""}
      </div>
      <div class="bubble">${
        options.pending ? `<p>${escapeHtml(content)}</p>` : formatAnswer(content)
      }</div>
    `;

    messagesEl.appendChild(article);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return article;
  }

  function setBusy(nextBusy) {
    busy = nextBusy;
    sendBtn.disabled = nextBusy;
    questionEl.disabled = nextBusy;
  }

  async function sendQuestion(question) {
    const trimmed = question.trim();
    if (!trimmed || busy) return;

    appendMessage("user", trimmed);
    questionEl.value = "";
    setBusy(true);

    const pending = appendMessage("agent", "Working with deterministic tools…", {
      pending: true,
      tag: "thinking",
    });

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          thread_id: threadId,
        }),
      });

      const payload = await response.json().catch(() => ({}));
      pending.remove();

      if (!response.ok) {
        const detail = payload.detail || "Request failed";
        appendMessage("agent", String(detail), { error: true, tag: "error" });
        return;
      }

      threadId = payload.thread_id;
      localStorage.setItem("airport_agent_thread_id", threadId);
      appendMessage("agent", payload.answer);
    } catch (error) {
      pending.remove();
      appendMessage(
        "agent",
        error instanceof Error ? error.message : "Network error",
        { error: true, tag: "error" }
      );
    } finally {
      setBusy(false);
      questionEl.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendQuestion(questionEl.value);
  });

  questionEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendQuestion(questionEl.value);
    }
  });

  document.querySelectorAll(".prompt-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt");
      if (prompt) sendQuestion(prompt);
    });
  });

  newChatBtn.addEventListener("click", () => {
    threadId = null;
    localStorage.removeItem("airport_agent_thread_id");
    messagesEl.innerHTML = "";
    appendMessage(
      "agent",
      "New thread started. Follow-ups from here stay in this conversation context.",
      { tag: "ready" }
    );
    questionEl.focus();
  });
})();
