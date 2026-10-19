// UI minimale : appelle POST api/v1/ask. Tout est rendu via textContent (pas d'innerHTML).
// URL relative par défaut : marche à la racine (/) comme sous un préfixe proxifié (/assistant/).
// Surchargeable avec <meta name="assistant-api-base" content="http://..."> si la page est hébergée ailleurs.
(function () {
  const meta = document.querySelector('meta[name="assistant-api-base"]');
  const base = ((meta && meta.content) || "").replace(/\/+$/, "");
  const askUrl = base ? base + "/api/v1/ask" : "api/v1/ask";
  const $ = (id) => document.getElementById(id);

  $("ask-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const question = $("question").value.trim();
    if (!question) return;
    $("submit").disabled = true;
    $("status").className = "";
    $("status").textContent = "Recherche en cours...";
    try {
      const res = await fetch(askUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error((data.error && data.error.message) || "Erreur " + res.status);
      $("answer").textContent = data.answer;
      $("degraded").hidden = !data.degraded;
      const list = $("sources");
      list.replaceChildren();
      data.sources.forEach((s) => {
        const li = document.createElement("li");
        const code = document.createElement("code");
        code.textContent = s.doc + (s.section ? " > " + s.section : "");
        const quote = document.createElement("blockquote");
        quote.textContent = s.extrait;
        li.append(code, quote);
        list.append(li);
      });
      $("result").hidden = false;
      $("status").textContent = "";
    } catch (err) {
      $("status").className = "error";
      $("status").textContent = err.message;
    } finally {
      $("submit").disabled = false;
    }
  });
})();
