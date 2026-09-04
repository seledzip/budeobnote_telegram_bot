/**
 * 부업노트 텔레그램 발행 봇 (Cloudflare Worker)
 *
 * 텔레그램에서 [발행하기] 버튼을 누르면:
 *  1. drafts/<slug>.html 내용을 가져와서
 *  2. posts/<slug>.html 로 생성
 *  3. index.html 에 카드 삽입
 *  4. sitemap.xml 에 url 블록 삽입
 *  5. drafts/<slug>.html 삭제
 *  6. 텔레그램에 완료 메시지 전송
 *
 * 필요한 Worker 환경변수(Secrets):
 *  - GITHUB_TOKEN            (repo 쓰기 권한 있는 GitHub Personal Access Token)
 *  - TELEGRAM_BOT_TOKEN
 *  - TELEGRAM_WEBHOOK_SECRET (임의의 문자열, setWebhook 시 secret_token으로 등록)
 *
 * 고정 설정값은 아래 CONFIG에서 저장소 이름 등을 수정하세요.
 */

const CONFIG = {
  owner: "seledzip",
  repo: "Celedzip",
  branch: "main",
  siteBase: "https://seledzip.github.io/Celedzip",
};

function toBase64(str) {
  const utf8 = new TextEncoder().encode(str);
  let binary = "";
  utf8.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary);
}

function fromBase64(b64) {
  const binary = atob(b64.replace(/\n/g, ""));
  const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

async function ghGet(env, path) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}?ref=${CONFIG.branch}`;
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "buopnote-bot",
      Accept: "application/vnd.github+json",
    },
  });
  console.log("GH_GET", path, res.status);
  if (!res.ok) return null;
  const json = await res.json();
  return { content: fromBase64(json.content), sha: json.sha };
}

async function ghPut(env, path, content, message, sha) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}`;
  const body = {
    message,
    content: toBase64(content),
    branch: CONFIG.branch,
  };
  if (sha) body.sha = sha;
  const res = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "buopnote-bot",
      Accept: "application/vnd.github+json",
    },
    body: JSON.stringify(body),
  });
  console.log("GH_PUT", path, res.status);
  if (!res.ok) {
    const t = await res.text();
    console.log("GH_PUT_ERROR", path, t);
    throw new Error(`GitHub PUT 실패 (${path}): ${res.status} ${t}`);
  }
  return res.json();
}

async function ghDelete(env, path, sha, message) {
  const url = `https://api.github.com/repos/${CONFIG.owner}/${CONFIG.repo}/contents/${path}`;
  const res = await fetch(url, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "buopnote-bot",
      Accept: "application/vnd.github+json",
    },
    body: JSON.stringify({ message, sha, branch: CONFIG.branch }),
  });
  console.log("GH_DELETE", path, res.status);
  if (!res.ok) {
    const t = await res.text();
    console.log("GH_DELETE_ERROR", path, t);
    throw new Error(`GitHub DELETE 실패 (${path}): ${res.status} ${t}`);
  }
}

async function telegramCall(env, method, payload) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const json = await res.json();
  console.log("TG_CALL_RESULT", method, json);
  return json;
}

function buildCardHtml(meta) {
  return `      <a class="post-card" href="posts/${meta.slug}.html">
        <span class="tag">${meta.tag}</span>
        <h3>${meta.title}</h3>
        <p>${meta.meta_description}</p>
        <div class="meta">읽는시간 ${meta.read_minutes}분 · ${meta.tag}</div>
      </a>
`;
}

function buildSitemapUrl(meta) {
  return `  <url>
    <loc>${CONFIG.siteBase}/posts/${meta.slug}.html</loc>
    <lastmod>${meta.date}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
`;
}

async function publishDraft(env, slug) {
  console.log("PUBLISH_START", slug);
  const draftPath = `drafts/${slug}.html`;
  const draft = await ghGet(env, draftPath);
  console.log("DRAFT_FETCHED", !!draft);
  if (!draft) throw new Error("초안을 찾을 수 없습니다. 이미 발행되었거나 삭제된 것 같습니다.");

  const metaMatch = draft.content.match(/<!-- DRAFT_META: (.*?) -->/s);
  if (!metaMatch) throw new Error("초안 메타데이터를 찾을 수 없습니다.");
  const meta = JSON.parse(metaMatch[1]);

  const finalContent = draft.content.replace(/<!-- DRAFT_META: .*? -->\n?/s, "");

  await ghPut(env, `posts/${slug}.html`, finalContent, `발행: ${meta.title}`);

  const indexFile = await ghGet(env, "index.html");
  const marker = "<!-- NEW_POST_MARKER -->";
  if (!indexFile.content.includes(marker)) {
    throw new Error(
      "index.html에서 <!-- NEW_POST_MARKER --> 를 찾을 수 없습니다. post-grid 시작 부분에 한 번 추가해주세요."
    );
  }
  const newIndexContent = indexFile.content.replace(
    marker,
    `${marker}\n${buildCardHtml(meta)}`
  );
  await ghPut(env, "index.html", newIndexContent, `index.html 카드 추가: ${meta.title}`, indexFile.sha);

  const sitemapFile = await ghGet(env, "sitemap.xml");
  const newSitemapContent = sitemapFile.content.replace(
    "</urlset>",
    `${buildSitemapUrl(meta)}</urlset>`
  );
  await ghPut(env, "sitemap.xml", newSitemapContent, `sitemap.xml 업데이트: ${meta.title}`, sitemapFile.sha);

  await ghDelete(env, draftPath, draft.sha, `초안 정리: ${meta.title}`);

  console.log("PUBLISH_DONE", slug);
  return meta;
}

async function discardDraft(env, slug) {
  const draftPath = `drafts/${slug}.html`;
  const draft = await ghGet(env, draftPath);
  if (!draft) return;
  await ghDelete(env, draftPath, draft.sha, `초안 삭제: ${slug}`);
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("OK - 부업노트 발행 봇이 실행 중입니다.", { status: 200 });
    }

    if (env.TELEGRAM_WEBHOOK_SECRET) {
      const header = (request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "").trim();
      const expected = env.TELEGRAM_WEBHOOK_SECRET.trim();
      if (header !== expected) {
        return new Response("Forbidden", { status: 403 });
      }
    }

    const update = await request.json();
    const cq = update.callback_query;

    if (cq && cq.data) {
      const [action, slug] = cq.data.split(":");
      console.log("ACTION_START", action, slug);

      try {
        if (action === "publish") {
          const meta = await publishDraft(env, slug);
          await telegramCall(env, "answerCallbackQuery", {
            callback_query_id: cq.id,
            text: "게시 완료!",
          });
          await telegramCall(env, "editMessageText", {
            chat_id: cq.message.chat.id,
            message_id: cq.message.message_id,
            text: `✅ *게시 완료*\n\n${meta.title}\n\n${CONFIG.siteBase}/posts/${meta.slug}.html`,
            parse_mode: "Markdown",
          });
        } else if (action === "discard") {
          await discardDraft(env, slug);
          await telegramCall(env, "answerCallbackQuery", {
            callback_query_id: cq.id,
            text: "삭제했습니다.",
          });
          await telegramCall(env, "editMessageText", {
            chat_id: cq.message.chat.id,
            message_id: cq.message.message_id,
            text: "🗑 초안을 삭제했습니다.",
          });
        }
      } catch (err) {
        console.log("ACTION_ERROR", err.message, err.stack);
        await telegramCall(env, "answerCallbackQuery", {
          callback_query_id: cq.id,
          text: "오류가 발생했습니다.",
          show_alert: true,
        });
        await telegramCall(env, "sendMessage", {
          chat_id: cq.message.chat.id,
          text: `⚠️ 오류: ${err.message}`,
        });
      }
    }

    return new Response("OK", { status: 200 });
  },
};