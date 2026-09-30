#!/usr/bin/env node
'use strict';

const http = require('http');
const readline = require('readline');
const fs = require('fs');
const path = require('path');

const argv = process.argv;
const urlIndex = argv.indexOf('--url');
const SERVER_URL = urlIndex !== -1 && argv[urlIndex + 1]
  ? argv[urlIndex + 1].replace(/\/$/, '')
  : 'http://192.168.8.131:8080';
const WEB_PORT = 3000;
const REPLAY = process.argv.indexOf('--replay');

// Логирование на диск с защитой от сбоев
const LOG_FILE = process.env.LLAMA_LOG_FILE || path.join(process.env.HOME || '.', 'llama-server.log');
const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });
logStream.on('error', (err) => {
  console.error('\x1b[31m[LOG STREAM ERROR]\x1b[0m', err.message);
});

const MAX_EVENTS = 500;
const MAX_HISTORY = 300;

// Полный декларативный сброс состояния таска — единственный источник формы
function freshTaskState() {
  return {
    id: null,
    totalPrompt: 0,
    lcpTokens: 0,
    lcpRatio: 0,
    kvRestoredTokens: 0,
    kvRestoredMiB: 0,
    deltaTokens: 0,
    prefillTokens: 0,
    prefillProgress: 0,
    prefillMs: 0,
    prefillTps: 0,
    generatedTokens: 0,
    decodeTps: 0,
    decodeTpsPeak: 0,
    decodeMs: 0,
    mtpAcceptance: 0,
    mtpMeanLen: 0,
    mtpPosAcc: [null, null, null, null, null],
    mtpAccepted: null,
    mtpGenerated: null,
    isTruncated: false,
    decodeStarted: false,
    prefillReported: false,
    kvEventEmitted: false,
    cachedFirstSeen: false,
    kvSource: null,
    lastProgressStep: 0
  };
}

const state = {
  serverUrl: SERVER_URL,
  serverOnline: false,
  n_ctx: 100096,
  n_prompt_tokens: 0,
  is_processing: false,
  currentStage: 'IDLE',
  _awaitingIdle: false,
  _doneSince: 0,
  _processingStart: 0,
  ramCache: {
    limitMiB: null,
    usedMiB: null,
    promptsCount: null,
    cpCreated: 0,
    cpErased: 0,
    cpCurrent: 0,
    cpMax: null,
    cpUsedMiB: 0,
    stateAt: null,
    promptCacheMiB: null,
    slots: {}
  },
  task: freshTaskState(),
  mtpN: 0,
  ngram: { accTokens: 0, genTokens: 0, meanLen: 0, posAcc: [] },
  history: [],
  events: []
};

// Буфер для изоляции LCP-сверки от предыдущего таска
let pendingLcp = null;
// Лучший кандидат из RAM-кэша (srv load, этап 2) до "found better prompt"
let pendingRamLcp = null;

const sseClients = new Set();
let stateDirty = false;
function snapshotJson() {
  state.serverNow = Date.now();
  return JSON.stringify(state);
}
function broadcastState() {
  stateDirty = true;
}
function flushState() {
  if (!stateDirty) return;
  stateDirty = false;
  // Без клиентов снимок не строим: новый клиент получит полный
  // снапшот при подключении к /events
  if (sseClients.size === 0) return;
  const payload = `data: ${snapshotJson()}\n\n`;
  for (const client of sseClients) {
    try {
      client.write(payload);
      if (typeof client.flush === 'function') client.flush();
    } catch (_) {
      sseClients.delete(client);
    }
  }
}
setInterval(flushState, 100);
function markOffline() {
  if (state.serverOnline) {
    state.serverOnline = false;
    broadcastState();
  }
}

// Привязка к таску: true, если в строке указан task id, отличный от текущего
// (защита от рассинхрона при быстром потоке запросов / чужих слотов)
function isForeignTask(line) {
  const m = line.match(/task\s+(\d+)/);
  return m !== null && state.task.id !== null && m[1] !== state.task.id;
}

function addEvent(stage, tag, title, detail, explicitTaskId = null, lifecycle = true) {
  const ts = new Date().toLocaleTimeString();
  if (lifecycle) state.currentStage = stage;
  const tid = explicitTaskId !== null ? String(explicitTaskId) : (state.task.id ? String(state.task.id) : 'SYS');
  const evId = Date.now() + Math.random();
  state.events.unshift({ ts, stage, tag, title, detail, id: evId, taskId: tid });
  if (state.events.length > MAX_EVENTS) state.events.pop();
  broadcastState();
  return evId;
}

// Дополняет событие SLOT SELECT источником KV, когда тот становится известен
// (RAM-чекпоинт / горячий VRAM-слот / cold start) — соответствующие строки
// приходят ПОСЛЕ выбора слота
function annotateSlotSelect(taskId, sourceHtml) {
  if (taskId == null) return;
  const ev = state.events.find(e => e.stage === 'PREFIX' && e.tag === 'SLOT SELECT' && e.taskId === String(taskId));
  if (ev) ev.detail += ' | Источник: ' + sourceHtml;
}

// Единая запись в историю: базовая форма из state.task + специфика ветки (extra)
function pushHistory(extra) {
  state.history.unshift(Object.assign({
    id: String(state.task.id || '—'),
    input: state.task.totalPrompt,
    lcp: state.task.lcpTokens,
    kvReuse: state.task.kvRestoredTokens,
    kvSource: state.task.kvSource || null,
    prefill: state.task.prefillTokens || state.task.deltaTokens,
    prefillSource: state.task.prefillTokens ? 'measured' : 'estimated',
    decode: state.task.generatedTokens,
    speed: state.task.decodeTps,
    total: state.task.totalPrompt + state.task.generatedTokens,
    isTruncated: Boolean(state.task.isTruncated),
    mtpAccepted: state.task.mtpAccepted || null,
    mtpGenerated: state.task.mtpGenerated || null,
    mtpAcceptance: state.task.mtpAcceptance || null,
    mtpMeanLen: state.task.mtpMeanLen || null,
    time: new Date().toLocaleTimeString()
  }, extra));
  if (state.history.length > MAX_HISTORY) state.history.pop();
}

function initNewTask(id, promptTokens) {
  pendingRamLcp = null;
  lastStallWarnSec = 0;
  state._awaitingIdle = false;
  state._processingStart = Date.now();
  state.task = freshTaskState();
  state.task.id = String(id);
  state.task.totalPrompt = promptTokens;

  // Публикуем LCP ровно один раз строго внутри карточки нового таска
  if (pendingLcp) {
    state.task.lcpRatio = pendingLcp.ratio;
    state.task.lcpTokens = pendingLcp.tokens || Math.round(promptTokens * pendingLcp.ratio);
    const tokStr = state.task.lcpTokens ? ` (${state.task.lcpTokens.toLocaleString()} ток.)` : '';
    addEvent('PREFIX', 'PREFIX', 'LCP Сверка истории', `Найдено совпадение: <b>${pendingLcp.pct}%</b>${tokStr}`, String(id));
    // SLOT SELECT: какой слот выбран по LCP и сколько токенов совпало.
    // Источник (RAM-чекпоинт / VRAM hot slot / cold start) дописывается позже —
    // соответствующие строки приходят после new prompt
    const slotStr = pendingLcp.slotId != null ? `Слот <b>#${pendingLcp.slotId}</b> · ` : '';
    addEvent('PREFIX', 'SLOT SELECT', 'Выбор слота по LCP', `${slotStr}LCP <b>${state.task.lcpTokens.toLocaleString()}</b> / ${promptTokens.toLocaleString()} ток. (${pendingLcp.pct}%)`, String(id));
    pendingLcp = null;
  } else {
    state.task.lcpTokens = 0;
    state.task.lcpRatio = 0;
  }

  state.task.deltaTokens = Math.max(0, promptTokens - state.task.lcpTokens);
}

const rl = readline.createInterface({ input: process.stdin, terminal: false });

function handleLine(line) {
  if (!line) return;

  // В replay-режиме не дописываем строки в LOG_FILE: иначе файл удваивается,
  // а реальные таймстемпы портят виртуальные часы следующих прогонов
  if (REPLAY === -1) {
    try {
      logStream.write(`[${new Date().toISOString()}] ${line}\n`);
    } catch (_) {}
  }

  // 1. Host RAM hit (srv load) — поиск в RAM-кэше
  // Строка: "I srv          load:  - found better prompt with f_keep = 1.000, f_sim = 0.999"
  if (line.includes('found better prompt')) {
    // Коммитим лучший кандидат из RAM — он переопределяет LCP этапа 1 (checking sim)
    if (pendingRamLcp) {
      pendingLcp = pendingRamLcp;
      pendingRamLcp = null;
    }
  }
  // 1b. Кандидаты srv load: "prompt with length   47328, lcp =   47328, f_keep = 1.000, f_sim = 0.999"
  else if (line.includes('prompt with length') && line.includes('lcp =')) {
    const m = line.match(/prompt with length\s+(\d+),\s*lcp\s*=\s*(\d+),\s*f_keep\s*=\s*([\d.]+),\s*f_sim\s*=\s*([\d.]+)/);
    if (m) {
      const total = parseInt(m[1], 10);
      const tokens = parseInt(m[2], 10);
      const ratio = total > 0 ? tokens / total : 0;
      if (!pendingRamLcp || tokens > pendingRamLcp.tokens) {
        pendingRamLcp = { ratio, tokens, pct: (ratio * 100).toFixed(1) };
      }
    }
  }

  // 2. PREFIX / LCP (буферизация до появления ID нового таска)
  if (line.includes('checking sim =') || line.includes('f_sim_best =')) {
    const m = line.match(/(?:checking sim|sim_best|f_sim_best)\s*=\s*([\d.]+)(?:\s*\((\d+)\/(\d+)\))?/);
    if (m) {
      const ratio = parseFloat(m[1]);
      const tokens = m[2] ? parseInt(m[2], 10) : 0;
      const pct = (ratio * 100).toFixed(1);

      // Сохраняем лучший результат для следующего таска, не создавая эвентов в старый
      if (line.includes('sim_best')) {
        // f_sim_best без (N/M): точный count — из checking sim того же кандидата (ratio совпал)
        const slotM = line.match(/\bid\s+(\d+)/);
        pendingLcp = { ratio, tokens: tokens || (pendingLcp && pendingLcp.ratio === ratio ? pendingLcp.tokens : 0), pct, slotId: slotM ? slotM[1] : null };
      } else if (!pendingLcp || ratio >= pendingLcp.ratio) {
        pendingLcp = { ratio, tokens, pct, slotId: pendingLcp ? pendingLcp.slotId : null };
      }
    }
  } 
  // 3. INPUT (старт таска)
  else if (line.includes('new prompt,') && (line.includes('task.n_tokens') || line.includes('n_prompt_tokens'))) {
    const m = line.match(/(?:task\s+(\d+).*?)?new prompt,.*?(?:task\.n_tokens|n_prompt_tokens)\s*=\s*(\d+)/);
    if (m) {
      const tid = m[1] || '0';
      const promptTokens = parseInt(m[2], 10);
      initNewTask(tid, promptTokens);
      addEvent('INPUT', 'INPUT', `Запрос #${tid}`, `Получено <b>${promptTokens.toLocaleString()}</b> Token IDs на CPU`, tid);
      console.log(`\x1b[36m⚡ [INPUT]\x1b[0m Запрос #${tid}: получено ${promptTokens} токенов`);
    }
  } 
  // 4. KV REUSE (Чекпоинты контекста физически поднимаются из Host RAM в VRAM!)
  else if (line.includes('restored context checkpoint')) {
    if (isForeignTask(line)) return;
    // n_tokens — истинное число восстановленных токенов (n_past совпадает);
    // pos_max = n_tokens - 1 (0-based позиция) — только fallback
    const mTokens = line.match(/n_tokens\s*=\s*(\d+)/) || line.match(/(?:n_past|pos_max)\s*=\s*(\d+)/);
    const mSize = line.match(/size\s*=\s*([\d.]+)\s*MiB/);
    const tokens = mTokens ? parseInt(mTokens[1], 10) : 0;
    const size = mSize ? mSize[1] : '0';

    state.task.kvRestoredTokens = tokens;
    state.task.kvRestoredMiB = parseFloat(size);
    state.task.kvSource = 'ram';
    state.task.deltaTokens = Math.max(0, state.task.totalPrompt - state.task.kvRestoredTokens);

    // Context Checkpoints (--ctx-checkpoints) ВСЕГДА хранятся в Host RAM (--cache-ram)!
    const tag = 'KV REUSE RAM';
    const source = 'Host RAM';

    // Если перед этим успело выставиться событие горячего VRAM слота, заменяем его на реальный подъем из RAM
    if (state.task.kvEventEmitted) {
      const inPlaceIdx = state.events.findIndex(
        e => e.stage === 'KV_RESTORE' && e.title === 'Кэш подтвержден' && e.taskId === String(state.task.id)
      );
      if (inPlaceIdx !== -1) state.events.splice(inPlaceIdx, 1);
    }
    state.task.kvEventEmitted = true;
    annotateSlotSelect(state.task.id, '<b>RAM-чекпоинт</b> (поднят в VRAM)');
    addEvent('KV_RESTORE', tag, 'Кэш поднят из RAM', `Восстановлено <b>${tokens.toLocaleString()}</b> ток. (${size} MiB) из <b>${source}</b> в VRAM.`);
    // Пульс на стойке чекпоинтов: этот слот только что поднят из RAM
    // (tokens здесь = pos_max, отличается от n_tokens на 1 → точное совпадение + fallback по близости)
    {
      const sl = state.ramCache.slots[tokens];
      if (sl) sl.lastRestored = Date.now();
      else {
        for (const k in state.ramCache.slots) {
          if (Math.abs(state.ramCache.slots[k].tokens - tokens) < 500) { state.ramCache.slots[k].lastRestored = Date.now(); break; }
        }
      }
    }
  }
  else if (line.includes('forcing full prompt re-processing')) {
    state.task.kvRestoredTokens = 0;
    state.task.kvSource = null;
    state.task.deltaTokens = state.task.totalPrompt;
    state.task.kvEventEmitted = true;
    annotateSlotSelect(state.task.id, 'нет (cold start)');
    addEvent('KV_RESTORE', 'KV MISS', 'Промах кэша / Cold start', `VRAM: <b>0</b> ток., RAM-чекпоинт: не найден. Полный prefill <b>${state.task.totalPrompt.toLocaleString()}</b> ток.`);
  }
  // 4b. In-Place VRAM hit (горячий слот): "slot operator(): ... | cached n_tokens = 60730, memory_seq_rm [...]"
  // Сервер НЕ восстанавливает чекпоинт — тензоры уже в VRAM, строка "restored context checkpoint" не пишется
  else if (line.includes('cached n_tokens =')) {
    if (isForeignTask(line)) return; // чужой таск (рассинхрон) — не трогаем текущее состояние
    if (!state.task.id) return; // монитор подключился посреди таска — границы нет, SYS-эвент не создаём
    const m = line.match(/cached n_tokens\s*=\s*(\d+)/);
    if (m) {
      const tokens = parseInt(m[1], 10);
      // Только ПЕРВАЯ строка cached после new prompt — начальное состояние кэша:
      // > 0 = горячий слот (KV уже в VRAM), == 0 = cold start.
      // Последующие значения — прогресс текущего prefill, не KV reuse.
      if (!state.task.cachedFirstSeen) {
        state.task.cachedFirstSeen = true;
        if (tokens > 0 && state.task.kvRestoredTokens === 0 && !state.task.kvEventEmitted) {
          state.task.kvRestoredTokens = tokens;
          state.task.kvSource = 'vram';
          state.task.deltaTokens = Math.max(0, state.task.totalPrompt - tokens);
          state.task.kvEventEmitted = true;
          annotateSlotSelect(state.task.id, '<b>VRAM hot slot</b>');
          addEvent('KV_RESTORE', 'KV REUSE VRAM', 'Кэш подтвержден', `В VRAM удержано <b>${tokens.toLocaleString()}</b> ток. (горячий слот).`);
        } else if (tokens === 0 && !state.task.kvEventEmitted) {
          // Явный cold start: ни горячего VRAM-слота, ни RAM-чекпоинта
          state.task.kvEventEmitted = true;
          annotateSlotSelect(state.task.id, 'нет (cold start)');
          addEvent('KV_RESTORE', 'KV MISS', 'Cold start', `VRAM: <b>0</b> ток., RAM-чекпоинт: не найден. Полный prefill с нуля.`);
        }
      }
    }
  }
  // 5. HOST RAM состояние (редкий авторитетный снапшот).
  // НЕ перезаписывает cpUsedMiB (живая оценка из created/erased) — только
  // целевой сброс слотов при полном очищении кэша (0 prompts, 0 MiB).
  else if (line.includes('cache state:')) {
    const m = line.match(/cache state:\s*(\d+)\s*prompts,\s*([\d.]+)\s*MiB\s*\(limits:\s*([\d.]+)\s*MiB/);
    if (m) {
      state.ramCache.promptsCount = parseInt(m[1], 10);
      state.ramCache.usedMiB = parseFloat(m[2]);
      state.ramCache.limitMiB = parseFloat(m[3]);
      state.ramCache.promptCacheMiB = parseFloat(m[2]);
      state.ramCache.stateAt = new Date().toISOString();
      if (state.ramCache.promptsCount === 0 && state.ramCache.usedMiB < 1) {
        state.ramCache.slots = {};
        state.ramCache.cpCurrent = 0;
        state.ramCache.cpUsedMiB = 0;
      }
      broadcastState();
    }
  }
  // 5b. Стойка чекпоинтов: слоты ключуются по n_tokens (стабильная идентичность).
  // Индекс «N of M» — это ПОЗИЦИЯ в живом списке (перенумеруется после erased),
  // поэтому как ключ НЕ подходит; M (cpMax) берём из строки.
  else if (line.includes('created context checkpoint')) {
    // выметаем вытесненные слоты после красной вспышки (2 с)
    for (const k in state.ramCache.slots) {
      const sl = state.ramCache.slots[k];
      if (sl.evictedAt && Date.now() - sl.evictedAt > 2000) delete state.ramCache.slots[k];
    }
    const m = line.match(/created context checkpoint\s+(\d+)\s+of\s+(\d+)/);
    const mTok = line.match(/n_tokens\s*=\s*(\d+)/);
    const mSize = line.match(/size\s*=\s*([\d.]+)\s*MiB/);
    if (m && mTok && mSize) {
      state.ramCache.cpCreated++;
      state.ramCache.cpMax = parseInt(m[2], 10);
      const tok = parseInt(mTok[1], 10);
      state.ramCache.slots[tok] = { tokens: tok, size: parseFloat(mSize[1]), time: Date.now(), lastRestored: null };
      state.ramCache.cpCurrent = Object.values(state.ramCache.slots).filter(s => !s.evictedAt).length;
      state.ramCache.cpUsedMiB = Object.values(state.ramCache.slots).filter(s => !s.evictedAt).reduce((a, s) => a + s.size, 0);
      // KV SAVE RAM: чекпоинт физически записан в Host RAM — привязываем к таску строки
      const mTask = line.match(/task\s+(\d+)/);
      addEvent('KV_RAM', 'KV SAVE RAM', 'Чекпоинт сохранен в RAM', `Слот <b>${m[1]} of ${m[2]}</b>: <b>${tok.toLocaleString()}</b> ток. (<b>${mSize[1]} MiB</b>)`, mTask ? mTask[1] : null, false);
    }
  }
  else if (line.includes('erased invalidated context checkpoint') || line.includes('erasing context checkpoint too close')) {
    // выметаем вытесненные слоты после красной вспышки (2 с)
    for (const k in state.ramCache.slots) {
      const sl = state.ramCache.slots[k];
      if (sl.evictedAt && Date.now() - sl.evictedAt > 2000) delete state.ramCache.slots[k];
    }
    state.ramCache.cpErased++;
    const mTok = line.match(/n_tokens\s*=\s*(\d+)/);
    const mSize = line.match(/size\s*=\s*([\d.]+)\s*MiB/);
    let evictSize = null;
    if (mTok) {
      const tok = parseInt(mTok[1], 10);
      let key = state.ramCache.slots[tok] ? tok : null;
      if (key === null) {
        let bestD = 200;
        for (const k in state.ramCache.slots) {
          const sl = state.ramCache.slots[k];
          if (sl.evictedAt) continue;
          const d = Math.abs(sl.tokens - tok);
          if (d < bestD) { bestD = d; key = k; }
        }
      }
      // не удаляем сразу: красная вспышка 2 с, потом выметается
      if (key !== null) {
        state.ramCache.slots[key].evictedAt = Date.now();
        evictSize = state.ramCache.slots[key].size;
      }
      state.ramCache.cpCurrent = Object.values(state.ramCache.slots).filter(s => !s.evictedAt).length;
      state.ramCache.cpUsedMiB = Object.values(state.ramCache.slots).filter(s => !s.evictedAt).reduce((a, s) => a + s.size, 0);
    }
    // KV EVICT RAM: чекпоинт физически стерт из Host RAM
    const reason = line.includes('erased invalidated') ? 'invalidated (контекст невалиден)' : 'capacity (too close к соседнему)';
    const sizeStr = mSize ? mSize[1] : (evictSize != null ? evictSize.toFixed(3) : '?');
    const mTask = line.match(/task\s+(\d+)/);
    addEvent('KV_RAM', 'KV EVICT RAM', 'Чекпоинт вытеснен из RAM', `<b>${mTok ? parseInt(mTok[1], 10).toLocaleString() : '?'}</b> ток. (<b>${sizeStr} MiB</b>) — причина: <b>${reason}</b>`, mTask ? mTask[1] : null, false);
  }
  else if (line.includes('prompt_save:') && line.includes('saving prompt with length')) {
    const m = line.match(/saving prompt with length\s*(\d+),\s*total state size\s*=\s*([\d.]+)\s*MiB/);
    if (m) {
      addEvent('PREFIX', 'RAM CACHE', 'Снимок диалога', `<b>${Number(m[1]).toLocaleString()}</b> ток. зафиксировано в Host RAM (${m[2]} MiB)`);
    }
  } 
  // 6. PREFILL
  else if (line.includes('prompt processing') && line.includes('progress =')) {
    if (isForeignTask(line)) return; // чужой таск (рассинхрон) — не трогаем текущее состояние
    const m = line.match(/n_tokens\s*=\s*(\d+).*?progress\s*=\s*([\d.]+)(?:.*?([\d.]+)\s*tokens per second)?/);
    if (m) {
      state.currentStage = 'PREFILL';
      const pct = Math.round(parseFloat(m[2]) * 100);
      state.task.prefillProgress = pct;
      if (m[3]) state.task.prefillTps = parseFloat(m[3]);
      
      const currentStep = Math.floor(pct / 25);
      if (currentStep > state.task.lastProgressStep && pct < 98) {
        state.task.lastProgressStep = currentStep;
        const spd = m[3] ? ` | Скорость: <b>${m[3]} tok/s</b>` : '';
        addEvent('PREFILL', 'PREFILL', `Префилл ${currentStep * 25}%`, `Обработано <b>${Number(m[1]).toLocaleString()}</b> ток.${spd}`);
      } else {
        broadcastState();
      }
    }
  } 
  // 7. SAMPLER — НЕ публикуем "префилл завершен" здесь:
  // реальное число токенов на GPU известно только из "prompt eval time" (ветка 8)
  else if (line.includes('init sampler, took') || line.includes('prompt processing done')) {
    state.currentStage = 'PREFILL';
    broadcastState();
  } 
  // 8. PREFILL TIMING
  else if (line.includes('prompt eval time =')) {
    const m = line.match(/prompt eval time\s*=\s*([\d.]+)\s*ms\s*\/\s*(\d+)\s*tokens.*?([\d.]+)\s*tokens per second/);
    if (m) {
      // Привязка к таску: в строке реальный task id — игнорируем рассинхрон из другого таска
      const tidM = line.match(/task\s+(\d+)/);
      if (tidM && state.task.id && tidM[1] !== state.task.id) {
        // Тайминг чужого таска (быстрый поток запросов) — не применяем к текущему
      } else {
        state.task.prefillMs = parseFloat(m[1]);
        state.task.prefillTokens = parseInt(m[2], 10);
        state.task.prefillTps = parseFloat(m[3]);

        const splitDetail = `Total: <b>${state.task.totalPrompt.toLocaleString()}</b> | KV reused: <b>${state.task.kvRestoredTokens.toLocaleString()}</b> | NEW: <b>${Number(m[2]).toLocaleString()}</b> ток. за ${m[1]} мс (<b>${m[3]} tok/s</b>)`;
        if (!state.task.prefillReported) {
          state.task.prefillReported = true;
          addEvent('PREFILL', 'PREFILL', 'Префилл завершен', splitDetail + ', начинается генерация.');
        } else {
          // Fallback (оценка по LCP) уже опубликован — заменяем на измеренный split
          const ev = state.events.find(e => e.stage === 'PREFILL' && e.tag === 'PREFILL' && e.title === 'Префилл завершен' && e.taskId === state.task.id);
          if (ev) ev.detail = splitDetail + ' (измерено)';
          broadcastState();
        }
      }
    }
  } 
  // 9. DECODE
  else if (line.includes('tg =') && (line.includes('n_gen =') || line.includes('n_decoded ='))) {
    if (isForeignTask(line)) return; // чужой таск (рассинхрон) — не трогаем текущее состояние
    const m = line.match(/(?:n_gen|n_decoded)\s*=\s*(\d+),\s*tg\s*=\s*([\d.]+)\s*t\/s(?:,\s*tg_3s\s*=\s*([\d.]+)\s*t\/s)?/);
    if (m) {
      state.currentStage = 'DECODE';
      state.task.generatedTokens = parseInt(m[1], 10);
      state.task.decodeTps = parseFloat(m[2]);
      if (m[3]) state.task.decodeTpsPeak = parseFloat(m[3]);

      if (!state.task.decodeStarted) {
        state.task.decodeStarted = true;
        // Fallback: если строка "prompt eval time" не попала в лог,
        // закрываем префилл оценкой (totalPrompt - LCP)
        if (!state.task.prefillReported) {
          state.task.prefillReported = true;
          const dTokens = state.task.deltaTokens || state.task.totalPrompt;
          addEvent('PREFILL', 'PREFILL', 'Префилл завершен', `Посчитано на GPU: ~<b>${Number(dTokens).toLocaleString()}</b> ток. (оценка по LCP), начинается генерация.`);
        }
        addEvent('DECODE', 'DECODE', 'Старт генерации', `Вывод начался (скорость: <b>${m[2]} t/s</b>)...`);
      } else {
        broadcastState();
      }
    }
  } 
  // 10. MTP
  else if (line.includes('draft acceptance =') || line.includes('draft acceptance rate =')) {
    if (isForeignTask(line)) return; // чужой таск (рассинхрон) — не трогаем текущее состояние
    const m = line.match(/draft acceptance(?:\s*rate)?\s*=\s*([\d.]+)\s*\(\s*(\d+)\s*accepted\s*\/\s*(\d+)\s*generated\)(?:,\s*mean len\s*=\s*([\d.]+))?/);
    if (m) {
      state.task.mtpAcceptance = (parseFloat(m[1]) * 100).toFixed(1);
      state.task.mtpMeanLen = m[4] ? parseFloat(m[4]) : 0;
      state.task.mtpAccepted = parseInt(m[2], 10);
      state.task.mtpGenerated = parseInt(m[3], 10);
      const lenText = m[4] ? ` | Длина: <b>${m[4]}</b> ток/такт` : '';
      // lifecycle=false: строка приходит ПОСЛЕ DONE и не должна двигать currentStage
      addEvent('MTP', 'MTP', 'Спекулятивный шаг', `Draft: <b>${m[3]}</b> сгенерировано, <b>${m[2]}</b> принято (<b>${state.task.mtpAcceptance}%</b>)${lenText}`, null, false);
      // Строка draft acceptance приходит ПОСЛЕ "eval time =" (DONE) —
      // запись истории уже создана: добираем MTP-поля по task id
      const h = (state.history || []).find(x => String(x.id) === String(state.task.id));
      if (h) {
        h.mtpAccepted = state.task.mtpAccepted;
        h.mtpGenerated = state.task.mtpGenerated;
        h.mtpAcceptance = state.task.mtpAcceptance;
        h.mtpMeanLen = state.task.mtpMeanLen;
      }
    }
  } 
  else if ((line.includes('acc per pos =') || line.includes('acc rate/pos =')) && !line.match(/statistics\s+ngram-mod:/)) {
    // Только статистика источника draft-mtp несёт истинные MTP-позиции:
    // длина кортежа == фактический --spec-draft-n-max запущенного сервера.
    // Per-task "acc per pos" (64 позиции, смесь ngram+MTP) и статистика
    // ngram-mod — не MTP, игнорируем.
    if (line.includes('draft-mtp:')) {
      const m = line.match(/acc rate\/pos\s*=\s*\(([-\d.,\s]+)\)/);
      if (m) {
        const vals = m[1].split(',').map(x => x.trim()).filter(Boolean).map(x => (parseFloat(x) * 100).toFixed(0));
        if (vals.length > 0) {
          state.mtpN = vals.length;
          state.task.mtpPosAcc = vals;
          broadcastState();
        }
      }
    }
  }
  // 10b. CANCEL (пользователь прервал запрос)
  else if (line.includes('cancel task') && line.includes('id_task =')) {
    const m = line.match(/id_task\s*=\s*(\d+)/);
    if (m) {
      const tid = m[1];
      if (state.task.id != null && String(state.task.id) === tid) {
        addEvent('CANCEL', 'CANCEL', 'Запрос отменен', `Генерация прервана пользователем (task <b>${tid}</b>).`, tid);
        pushHistory({ cancelled: true, isTruncated: false });
        state.currentStage = 'DONE';
        state._awaitingIdle = true;
        state._doneSince = Date.now();
        setTimeout(() => {
          if (state._awaitingIdle && !state.is_processing) {
            state._awaitingIdle = false;
            state.currentStage = 'IDLE';
            broadcastState();
          }
        }, 1500);
      } else {
        // отмена уже завершённого/исторического таска — помечаем запись
        const h = (state.history || []).find(x => String(x.id) === tid);
        if (h) h.cancelled = true;
      }
    }
  }
  // 10c. NGRAM-MOD статистика (второй источник спекуляции, каждые 100 вызовов)
  // Формат: "statistics        ngram-mod:" — множественные пробелы (logfmt), поэтому regex
  else if (line.match(/statistics\s+ngram-mod:/)) {
    const mAcc = line.match(/#acc tokens\s*=\s*(\d+)/);
    const mGen = line.match(/#gen tokens\s*=\s*(\d+)/);
    const mLen = line.match(/#mean acc len\s*=\s*([\d.]+)/);
    const mPos = line.match(/#acc rate\/pos\s*=\s*\(([-\d.,\s]+)\)/);
    state.ngram.accTokens = mAcc ? parseInt(mAcc[1], 10) : 0;
    state.ngram.genTokens = mGen ? parseInt(mGen[1], 10) : 0;
    state.ngram.meanLen = mLen ? parseFloat(mLen[1]) : 0;
    if (mPos) state.ngram.posAcc = mPos[1].split(',').map(x => x.trim()).filter(Boolean);
    broadcastState();
  }
  // 11. DONE
  else if (line.includes('stop processing:') && line.includes('truncated =')) {
    const m = line.match(/truncated\s*=\s*(\d+)/);
    if (m && parseInt(m[1], 10) > 0) {
      state.task.isTruncated = true;
      addEvent('DONE', 'OVERFLOW', 'Лимит контекста', 'Контекст переполнен!');
    }
  } 
  else if (line.includes('eval time =') && !line.includes('prompt eval')) {
    const m = line.match(/eval time\s*=\s*([\d.]+)\s*ms\s*\/\s*(\d+)\s*tokens.*?([\d.]+)\s*tokens per second/);
    if (m) {
      // Привязка к таску: в строке реальный task id — игнорируем рассинхрон из другого таска
      const tidM = line.match(/task\s+(\d+)/);
      if (tidM && state.task.id && tidM[1] !== state.task.id) {
        // Финальный тайминг чужого таска (быстрый поток запросов) — не применяем к текущему
      } else {
        state.task.decodeMs = parseFloat(m[1]);
        state.task.generatedTokens = parseInt(m[2], 10);
        state.task.decodeTps = parseFloat(m[3]);
        state.currentStage = 'DONE';
        state._awaitingIdle = true;
        state._doneSince = Date.now();

        // Короткий ответ (<3с): сервер не шлет промежуточные "n_gen =" строки
        // (таймер прогресса 3с), поэтому событие DECODE не было опубликовано — догоняем
        if (!state.task.decodeStarted) {
          state.task.decodeStarted = true;
          addEvent('DECODE', 'DECODE', 'Старт генерации', `Вывод завершен мгновенно (скорость: <b>${m[3]} t/s</b>)...`);
        }

        const peakStr = state.task.decodeTpsPeak ? ` | пик <b>${state.task.decodeTpsPeak} t/s</b>` : '';
        addEvent('DONE', 'DONE', 'Ответ завершен', `Сгенерировано <b>${m[2]}</b> ток. за ${(parseFloat(m[1]) / 1000).toFixed(2)} с | средн. <b>${m[3]} t/s</b>${peakStr}`);
        console.log(`\x1b[32m✔ [DONE]\x1b[0m Сгенерировано ${m[2]} токенов со скоростью ${m[3]} t/s`);

        pushHistory({});

        setTimeout(() => {
          if (state._awaitingIdle && !state.is_processing) {
            state._awaitingIdle = false;
            state.currentStage = 'IDLE';
            broadcastState();
          }
        }, 1500);
      }
    }
  }
}
rl.on('line', handleLine);

let serverPollBusy = false;
let lastStallWarnSec = 0;
async function pollServer() {
  if (serverPollBusy) return;
  serverPollBusy = true;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 400);
    const res = await fetch(`${SERVER_URL}/slots`, { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (Array.isArray(data) && data.length > 0) {
      const slot = data.find(s => s.is_processing) || data[0];
      const prevOnline = state.serverOnline;
      const prevUsed = state.n_prompt_tokens;
      const prevProc = state.is_processing;
      const prevDecoded = state.task.generatedTokens;

      state.serverOnline = true;
      state.n_ctx = slot.n_ctx || 100096;
      state.n_prompt_tokens = slot.n_prompt_tokens || 0;
      state.is_processing = Boolean(slot.is_processing);

      // Плавное обновление счетчика декода из /slots (только значение,
      // никакого влияния на currentStage — жизненный цикл управляется
      // исключительно строками из stdin)
      if (state.is_processing && Number.isFinite(slot.n_decoded) && slot.n_decoded > state.task.generatedTokens) {
        state.task.generatedTokens = slot.n_decoded;
      }

      // Детектор затяжного префилла
      if (state.is_processing && state._processingStart > 0) {
        const elapsedSec = Math.round((Date.now() - state._processingStart) / 1000);
        // Защита от дребезга: pollServer ходит каждые 500 мс, одна и та же секунда
        // могла попасть в проверку дважды
        if (elapsedSec > 60 && elapsedSec % 60 === 0 && state.currentStage === 'PREFILL' && elapsedSec !== lastStallWarnSec) {
          lastStallWarnSec = elapsedSec;
          addEvent('PREFILL', 'STALL_WARN', 'Долгая пауза префилла', `Слот занят уже <b>${elapsedSec}с</b> без перехода к детекции/декоду!`);
        }
      }

      if (!prevOnline || prevUsed !== state.n_prompt_tokens || prevProc !== state.is_processing || prevDecoded !== state.task.generatedTokens) {
        broadcastState();
      }
    } else {
      markOffline();
    }
  } catch (_) {
    markOffline();
  } finally {
    serverPollBusy = false;
  }
}
if (REPLAY === -1) {
  setInterval(pollServer, 500);
  pollServer();
}

const HTML_PAGE = `
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Llama.cpp Canonical Engine Monitor</title>
<style>
:root{
  --bg:#06090e;--panel:#0d131d;--panel2:#090e15;--border:#1a2436;--text:#f1f5f9;--dim:#64748b;
  --input:#38bdf8;--prefix:#39c5cf;--reuse:#22c55e;--prefill:#eab308;--decode:#a855f7;--red:#ef4444;
}
*{box-sizing:border-box}
html,body{height:100%;margin:0;padding:12px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,monospace;background:var(--bg);color:var(--text);display:flex;flex-direction:column;overflow:hidden}
.top-bar{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:8px;flex-shrink:0}
.badge{padding:3px 9px;border-radius:6px;font-size:11.5px;font-weight:bold}.badge-on{background:#15803d;color:#fff}.badge-off{background:#b91c1c;color:#fff}.badge-warn{background:#dc2626;color:#fff;animation:blink 1s infinite}@keyframes blink{50%{opacity:.5}}
.legend-bar{display:flex;gap:6px;justify-content:space-between;background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:6px 12px;margin-bottom:10px;font-size:11px;flex-shrink:0}.legend-cell{display:flex;align-items:center;gap:5px}.tag-pill{padding:2px 6px;border-radius:4px;font-weight:bold;font-size:10.5px}
.main-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 0.95fr 1.25fr; gap: 12px; }
.left-col { display: flex; flex-direction: column; gap: 10px; min-height: 0; height: 100%; }
.right-col { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 9px; padding: 12px; position: relative; }
.card-history { flex: 1; min-height: 120px; display: flex; flex-direction: column; }
.card-log { flex: 1; min-height: 0; height: 100%; display: flex; flex-direction: column; }
.donut-layout{display:flex;align-items:center;gap:18px}.donut-box{position:relative;width:200px;height:200px;flex-shrink:0}.donut-box canvas{width:200px;height:200px;display:block}
.donut-core { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; border-radius: 50%; pointer-events: none; overflow: hidden; }
.donut-core::after { content: ""; position: absolute; inset: 0; border-radius: 50%; background: radial-gradient(circle, rgba(56,189,248,.35) 0%, transparent 70%); opacity: 0; pointer-events: none; transition: opacity .4s ease; }
.donut-core.breathe-idle::after { animation: breatheGlow 3.2s ease-in-out infinite; }
@keyframes breatheGlow { 0%, 100% { opacity: 0.15; transform: scale(0.95); } 50% { opacity: 0.85; transform: scale(1.05); } }
.phase-badge{font-size:11px;font-weight:bold;padding:2px 10px;border-radius:20px;background:#151e2b;color:var(--text);border:1px solid var(--border);margin-bottom:2px;transition:all .25s ease}
.live-speed{font-size:18px; font-weight:bold; color:#fff; margin:1px 0; white-space: nowrap;}
.live-pct{font-size:11px;color:var(--dim)}
.phase-IDLE { box-shadow: 0 0 0 1px rgba(100,116,139,.4), 0 0 16px rgba(56,189,248,.25); }
.phase-INPUT { box-shadow: 0 0 0 1px var(--input), 0 0 20px rgba(56,189,248,.55); color: var(--input); }
.phase-PREFIX, .phase-KV_RESTORE { box-shadow: 0 0 0 1px var(--reuse), 0 0 20px rgba(34,197,94,.55); color: var(--reuse); }
.phase-PREFILL { box-shadow: 0 0 0 1px var(--prefill), 0 0 20px rgba(234,179,8,.55); color: var(--prefill); }
.phase-DECODE { box-shadow: 0 0 0 1px var(--decode), 0 0 20px rgba(168,85,247,.6); color: var(--decode); }
.phase-MTP { box-shadow: 0 0 0 1px var(--prefix), 0 0 20px rgba(57,197,207,.55); color: var(--prefix); }
.phase-DONE { box-shadow: 0 0 0 1px var(--reuse), 0 0 16px rgba(34,197,94,.4); color: var(--reuse); }
.donut-legend{flex:1;display:flex;flex-direction:column;gap:5px}.legend-row{display:flex;justify-content:space-between;align-items:center;background:#090e15;padding:5px 10px;border-radius:5px;border:1px solid var(--border);transition:all .25s ease}.legend-row.active-row{border-color:var(--input);background:#121b28}.legend-title{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:bold}.dot{width:8px;height:8px;border-radius:2px}.legend-val{font-size:12.5px;font-weight:bold;color:#fff}
.bar-bg{display:flex;height:14px;border-radius:4px;overflow:hidden;background:#16202f;border:1px solid var(--border);margin:4px 0}.bar-seg{height:100%;transition:width .35s ease}
.mtp-grid{display:flex;gap:4px;margin-top:4px}.mtp-item{flex:1 1 auto;text-align:center;font-size:10px}
.mtp-col{background:#16202f;height:36px;display:flex;align-items:flex-end;border-radius:3px;overflow:hidden;border:1px solid var(--border)}
.mtp-fill{width:100%;background:var(--prefix);transition:height .35s cubic-bezier(0.4, 0, 0.2, 1)}
.log-box { flex: 1; height: 100%; min-height: 0; overflow-y: auto; overflow-anchor: none; background: #04070b; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-family: monospace; font-size: 12px; }
.task-card { background: #090e16; border: 1px solid #1a2538; border-radius: 7px; margin-bottom: 8px; overflow: hidden; transition: all 0.25s ease; }
.task-card.active-task-card { border-color: var(--input); box-shadow: 0 0 12px rgba(56,189,248,0.22); }
.task-card.highlight-pulse { border-color: var(--input) !important; box-shadow: 0 0 18px var(--input) !important; animation: taskPulse 1.2s ease-out 1; }
@keyframes taskPulse { 0% { transform: scale(0.985); } 50% { transform: scale(1.01); } 100% { transform: scale(1); } }
.task-card-header { display: flex; justify-content: space-between; align-items: center; background: #0d1522; padding: 6px 10px; cursor: pointer; border-bottom: 1px solid #162030; font-size: 11.5px; }
.task-card-header:hover { background: #131f30; }
.task-card-title { display: flex; align-items: center; gap: 8px; font-weight: bold; }
.task-badge-id { background: #1a273b; color: var(--input); padding: 2px 7px; border-radius: 4px; font-size: 11px; border: 1px solid rgba(56,189,248,0.3); }
.task-card-summary { font-size: 11px; color: var(--dim); }
.task-card-body { padding: 4px 6px; display: flex; flex-direction: column; gap: 3px; }
.log-row { margin: 1px 0; padding: 4px 8px; border-radius: 4px; background: #070b12; border-left: 3px solid var(--border); display: flex; align-items: baseline; gap: 10px; line-height: 1.35; font-size: 11.5px; }
.log-time { width: 80px; min-width: 80px; flex-shrink: 0; color: var(--dim); font-variant-numeric: tabular-nums; font-size: 11px; }
.log-tag { width: 108px; min-width: 108px; flex-shrink: 0; text-align: center; display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; font-size: 10px; padding: 2px 4px; border-radius: 4px; font-weight: bold; letter-spacing: 0.2px; }
.log-msg { flex: 1; min-width: 0; word-break: break-word; }
.log-row.INPUT { border-left-color: var(--input); }
.log-row.INPUT .log-tag { background: rgba(56,189,248,.18); color: var(--input); border: 1px solid var(--input); }
.log-row.PREFIX,.log-row.MTP { border-left-color: var(--prefix); }
.log-row.PREFIX .log-tag,.log-row.MTP .log-tag { background: rgba(57,197,207,.18); color: var(--prefix); border: 1px solid var(--prefix); }
.log-row.KV_RESTORE { border-left-color: var(--reuse); }
.log-row.KV_RESTORE .log-tag { background: rgba(34,197,94,.18); color: var(--reuse); border: 1px solid var(--reuse); }
.log-row.KV_RESTORE[data-tag="KV REUSE RAM"] { border-left-color: var(--prefix); }
.log-row.KV_RESTORE[data-tag="KV REUSE RAM"] .log-tag { background: rgba(57,197,207,.2); color: var(--prefix); border-color: var(--prefix); }
.log-row.KV_RAM { border-left-color: #39c9cf; }
.log-row.KV_RAM .log-tag { background: rgba(57,201,207,.18); color: #39c9cf; border: 1px solid #39c9cf; }
.log-row.KV_RESTORE[data-tag="KV MISS"] { border-left-color: var(--red); }
.log-row.KV_RESTORE[data-tag="KV MISS"] .log-tag { background: rgba(239,68,68,.2); color: var(--red); border-color: var(--red); }
.log-row.PREFILL { border-left-color: var(--prefill); }
.log-row.PREFILL .log-tag { background: rgba(234,179,8,.18); color: var(--prefill); border: 1px solid var(--prefill); }
.log-row.DECODE { border-left-color: var(--decode); }
.log-row.DECODE .log-tag { background: rgba(168,85,247,.18); color: var(--decode); border: 1px solid var(--decode); }
.log-row.DONE { border-left-color: var(--reuse); }
.log-row.DONE .log-tag { background: rgba(34,197,94,.18); color: var(--reuse); border: 1px solid var(--reuse); }
.log-row.CANCEL { border-left-color: var(--red); }
.log-row.CANCEL .log-tag { background: rgba(239,68,68,.2); color: var(--red); border: 1px solid var(--red); }
.log-row.PREFILL .log-tag[style*="red"] { background: rgba(239,68,68,.2); color: var(--red); border-color: var(--red); }
.table-wrap{flex:1;height:100%;min-height:0;overflow-y:auto}.hist-table{width:100%;border-collapse:collapse;font-size:11px;font-family:monospace}.hist-table th,.hist-table td{padding:5px 6px;text-align:left;border-bottom:1px solid var(--border);cursor:pointer}.hist-table th{color:var(--dim);position:sticky;top:0;background:var(--panel)}.hist-table tr:hover td{background:#131c2b}
.hist-row-highlight { background: rgba(56,189,248,0.18) !important; outline: 1px solid var(--input); }
</style>
</head>
<body>
  <div class="top-bar">
    <div><h1 style="margin:0; font-size:16px; color:var(--input); font-weight:bold;">LLAMA.CPP CANONICAL ENGINE MONITOR</h1></div>
    <div style="display:flex; gap:10px; align-items:center;">
      <div id="overflow-badge" class="badge badge-warn" style="display:none;">CONTEXT OVERFLOW</div>
      <div id="status-badge" class="badge badge-off">CONNECTING...</div>
    </div>
  </div>
  <div class="legend-bar">
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(56,189,248,.2); color:var(--input); border:1px solid var(--input)">INPUT</span> <span style="color:var(--dim)">Промпт (CPU)</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(57,197,207,.2); color:var(--prefix); border:1px solid var(--prefix)">PREFIX</span> <span style="color:var(--dim)">LCP Сверка</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(34,197,94,.2); color:var(--reuse); border:1px solid var(--reuse)">KV REUSE</span> <span style="color:var(--dim)">Готовые K,V (0 мс)</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(57,201,207,.2); color:#39c9cf; border:1px solid #39c9cf">KV RAM</span> <span style="color:var(--dim)">Чекпоинты (save/evict)</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(234,179,8,.2); color:var(--prefill); border:1px solid var(--prefill)">PREFILL</span> <span style="color:var(--dim)">Дельта на GPU</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(168,85,247,.2); color:var(--decode); border:1px solid var(--decode)">DECODE</span> <span style="color:var(--dim)">Вывод (Q × K_all)</span></div>
    <div class="legend-cell"><span class="tag-pill" style="background:rgba(57,197,207,.2); color:var(--prefix); border:1px solid var(--prefix)">MTP</span> <span style="color:var(--dim)">Спекуляция</span></div>
  </div>
  <div class="main-layout">
    <div class="left-col">
      <div class="card" style="padding:10px 12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <span style="font-size:12px; font-weight:bold;">GPU VRAM KV-SLOT (<span id="hdr-ctx">100,096</span> CELLS)</span>
          <span style="font-size:11px; color:var(--dim);">Total Input: <b id="val-input" style="color:var(--input)">0</b> ток.</span>
        </div>
        <div class="donut-layout">
          <div class="donut-box">
            <canvas id="reactor-canvas" width="400" height="400"></canvas>
            <div class="donut-core" id="donut-core-bg">
              <div id="core-phase" class="phase-badge">IDLE</div>
              <div id="core-speed" class="live-speed">—</div>
              <div id="core-pct" class="live-pct">0 / 100k (0%)</div>
            </div>
          </div>
          <div class="donut-legend">
            <div class="legend-row" id="row-reuse">
              <div class="legend-title" style="color:var(--reuse)"><div class="dot" style="background:var(--reuse)"></div><span>KV REUSE:</span></div>
              <div class="legend-val" id="val-cached" style="color:var(--reuse)">0</div>
            </div>
            <div class="legend-row" id="row-prefill">
              <div class="legend-title" style="color:var(--prefill)"><div class="dot" style="background:var(--prefill)"></div><span>PREFILL:</span></div>
              <div class="legend-val" id="val-delta" style="color:var(--prefill)">0</div>
            </div>
            <div class="legend-row" id="row-decode">
              <div class="legend-title" style="color:var(--decode)"><div class="dot" style="background:var(--decode)"></div><span>DECODE:</span></div>
              <div class="legend-val" id="val-gen" style="color:var(--decode)">0</div>
            </div>
            <div class="legend-row" style="background:transparent; border:none; padding:1px 0;">
              <div class="legend-title" style="color:var(--dim)"><span>FREE:</span></div>
              <div class="legend-val" id="val-free" style="color:var(--dim)">100,096 ток.</div>
            </div>
          </div>
        </div>
        <div style="margin-top:8px;">
          <div style="font-size:10.5px; color:var(--dim); margin-bottom:3px;">Лента контекста 0 → <span id="lbl-tape-total">…</span> ток. · проекция чекпоинтов RAM</div>
          <div id="tape-bar" style="position:relative; height:16px; background:#0b111a; border-radius:3px; overflow:hidden;">
            <div id="tape-reuse" style="position:absolute; left:0; top:0; bottom:0; width:0%; background:var(--reuse); opacity:0.85;"></div>
            <div id="tape-prefill" style="position:absolute; top:0; bottom:0; width:0%; background:var(--prefill); opacity:0.85;"></div>
            <div id="tape-decode" style="position:absolute; top:0; bottom:0; width:0%; background:var(--decode); opacity:0.85;"></div>
            <div id="tape-ticks" style="position:absolute; inset:0;"></div>
          </div>
          <div style="display:flex; justify-content:space-between; font-size:10.5px; margin-top:3px;">
            <span style="color:var(--reuse)">▲ REUSE <b id="lbl-tape-reuse">0</b></span>
            <span style="color:var(--prefill)">▲ PREFILL <b id="lbl-tape-prefill">0</b></span>
            <span style="color:var(--decode)">▲ DECODE <b id="lbl-tape-decode">0</b></span>
            <span style="color:var(--dim)">░ FREE <b id="lbl-tape-free">0</b></span>
          </div>
        </div>
      </div>
      <div class="card" style="padding:8px 12px;">
        <div style="font-size:11.5px; font-weight:bold; margin-bottom:2px;">HOST RAM PROMPT CACHE (<span id="lbl-ram-limit-title">…</span>)</div>
        <div class="bar-bg" style="display:flex;">
          <div id="bar-ram-cp" class="bar-seg" style="width:0%; background:#39c9cf;"></div>
          <div id="bar-ram-prompt" class="bar-seg" style="width:0%; background:var(--prefix);"></div>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:11px;">
          <span>Чекпоинты: <b id="lbl-cp-mib" style="color:#39c9cf">0 MiB</b></span>
          <span>Снапшот: <b id="lbl-ram-snap-mib" style="color:var(--prefix)">N/A</b> / <span id="lbl-ram-limit">…</span> MiB</span>
        </div>
        <div id="checkpoint-grid" style="display:grid; grid-template-columns:repeat(16,1fr); gap:3px; margin:6px 0 4px;"></div>
        <div style="display:flex; justify-content:space-between; font-size:10.5px; color:var(--dim);">
          <span>Слоты: <b id="lbl-cp" style="color:var(--prefix)">0/—</b> | оборот: <span id="lbl-cp-churn">+0 / −0</span></span>
          <span>Снапшот <span id="lbl-ram-at">—</span>: <span id="lbl-ram-snap">N/A</span></span>
        </div>
      </div>
      <div class="card" style="padding:8px 12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-size:11.5px; font-weight:bold; color:var(--prefix);">MTP SPECULATIVE DRAFT (1–<span id="lbl-mtp-n">…</span>)</div>
          <span id="lbl-mtp-step" style="font-size:11px; color:var(--prefix); font-weight:bold;">— ток/такт</span>
        </div>
        <div class="mtp-grid" id="mtp-bars"></div>
      </div>
      <div class="card" style="padding:8px 12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="font-size:11.5px; font-weight:bold; color:var(--prefix);">NGRAM-MOD SPEC <span style="font-size:9px; color:var(--dim); font-weight:normal;">(CUMULATIVE)</span></div>
          <span id="lbl-ngram" style="font-size:11px; color:var(--prefix); font-weight:bold;">—</span>
        </div>
      </div>
      <div class="card card-history" style="padding:8px 12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
          <div style="font-size:11.5px; font-weight:bold;">REQUEST HISTORY <span style="font-weight:normal; color:var(--dim); font-size:10.5px;">(до 300 записей)</span></div>
          <a href="/api/logs" target="_blank" style="color:var(--input); font-size:10.5px; text-decoration:none;">📄 Открыть raw log</a>
        </div>
        <div class="table-wrap">
          <table class="hist-table">
            <thead>
              <tr><th>TIME</th><th>TASK</th><th style="color:var(--input)">INPUT</th><th style="color:var(--reuse)">KV REUSE</th><th style="color:var(--prefill)">PREFILL</th><th style="color:var(--decode)">DECODE</th><th style="color:var(--prefix)">MTP</th><th>SPEED</th></tr>
            </thead>
            <tbody id="hist-rows"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="right-col">
      <div class="card card-log">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <div style="font-size:12px; font-weight:bold;">EVENT LOG (GPU & RAM TELEMETRY)</div>
          <div style="font-size:10.5px; color:var(--dim);">Глубина: 500 событий</div>
        </div>
        <div class="log-box" id="log-feed"></div>
      </div>
    </div>
  </div>
  <script>
  (() => {
    const cvs = document.getElementById('reactor-canvas');
    const ctx = cvs.getContext('2d');
    const CX = 200, CY = 200, R = 150, LW = 36;
    const START = -Math.PI / 2;

    let anim = { cached: 0, delta: 0, gen: 0, total: 100096 };
    let target = { cached: 0, delta: 0, gen: 0, total: 100096 };
    let animRunning = false;
    function kick() {
      if (animRunning) return;
      animRunning = true;
      requestAnimationFrame(drawReactor);
    }

    const mtpContainer = document.getElementById('mtp-bars');
    let renderedMtpN = 0;
    function buildMtpBars(n) {
      mtpContainer.innerHTML = Array.from({length: n}, (_, i) =>
        '<div class="mtp-item">' +
          '<div class="mtp-col"><div class="mtp-fill" id="mtp-f' + i + '" style="height:0%"></div></div>' +
          '<div style="margin-top:2px">P' + (i + 1) + '</div>' +
          '<div id="mtp-v' + i + '" style="color:var(--prefix);font-weight:bold">—</div>' +
        '</div>'
      ).join('');
      renderedMtpN = n;
    }
    buildMtpBars(5); // плейсхолдер, пока первая draft-mtp статистика не задаст mtpN

    const cpGrid = document.getElementById('checkpoint-grid');
    let renderedCpMax = 0;
    function buildCpGrid(n) {
      if (!cpGrid) return;
      cpGrid.style.gridTemplateColumns = 'repeat(' + Math.min(16, n) + ',1fr)';
      cpGrid.innerHTML = '';
      for (let i = 0; i < n; i++) {
        const c = document.createElement('div');
        c.id = 'cp-cell-' + i;
        c.style.height = '10px';
        c.style.borderRadius = '2px';
        c.style.background = '#0b111a';
        c.style.opacity = '0.35';
        cpGrid.appendChild(c);
      }
      renderedCpMax = n;
    }
    buildCpGrid(32); // плейсхолдер, пока первая created-строка не задаст cpMax

    function drawReactor() {
      anim.cached += (target.cached - anim.cached) * 0.15;
      anim.delta += (target.delta - anim.delta) * 0.15;
      anim.gen += (target.gen - anim.gen) * 0.15;
      anim.total = target.total || 100096;

      const settled = Math.abs(anim.cached - target.cached) < 0.5 &&
                      Math.abs(anim.delta - target.delta) < 0.5 &&
                      Math.abs(anim.gen - target.gen) < 0.5;
      if (settled) {
        anim.cached = target.cached;
        anim.delta = target.delta;
        anim.gen = target.gen;
      }

      ctx.clearRect(0, 0, 400, 400);
      ctx.lineWidth = LW;
      ctx.strokeStyle = '#151e2b';
      ctx.beginPath();
      ctx.arc(CX, CY, R, 0, Math.PI * 2);
      ctx.stroke();

      const cachedAngle = (anim.cached / anim.total) * (Math.PI * 2);
      const deltaAngle = (anim.delta / anim.total) * (Math.PI * 2);
      const genAngle = (anim.gen / anim.total) * (Math.PI * 2);

      if (anim.cached > 2) {
        ctx.strokeStyle = '#22c55e';
        ctx.beginPath();
        ctx.arc(CX, CY, R, START, START + cachedAngle);
        ctx.stroke();
      }
      if (anim.delta > 2) {
        const sA = START + cachedAngle;
        const eA = sA + deltaAngle;
        ctx.strokeStyle = '#eab308';
        ctx.beginPath();
        ctx.arc(CX, CY, R, sA, eA);
        ctx.stroke();
      }
      if (anim.gen > 2) {
        const sA = START + cachedAngle + deltaAngle;
        const eA = sA + genAngle;
        ctx.strokeStyle = '#a855f7';
        ctx.beginPath();
        ctx.arc(CX, CY, R, sA, eA);
        ctx.stroke();
      }

      if (settled) {
        animRunning = false;
        return;
      }
      requestAnimationFrame(drawReactor);
    }
    kick();

    function esc(v) {
      return String(v ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));
    }
    function num(v, def = 0) { const n = Number(v); return Number.isFinite(n) ? n : def; }

    let lastEventsHash = '';
    let lastHistHash = '';
    let lastTicksHtml = '';

    function focusTask(taskId) {
      if (!taskId) return;
      const card = document.getElementById('task-card-' + taskId);
      const row = document.getElementById('hist-row-' + taskId);
      
      document.querySelectorAll('.hist-table tbody tr').forEach(r => r.classList.remove('hist-row-highlight'));
      if (row) row.classList.add('hist-row-highlight');

      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        card.classList.remove('highlight-pulse');
        void card.offsetWidth;
        card.classList.add('highlight-pulse');
        card.addEventListener('animationend', () => {
          card.classList.remove('highlight-pulse');
        }, { once: true });
      }
    }

    document.getElementById('log-feed').addEventListener('click', (e) => {
      const header = e.target.closest('.task-card-header');
      if (header && header.dataset.taskId) {
        focusTask(header.dataset.taskId);
      }
    });

    document.getElementById('hist-rows').addEventListener('click', (e) => {
      const row = e.target.closest('tr[data-task-id]');
      if (row && row.dataset.taskId) {
        focusTask(row.dataset.taskId);
      }
    });

    function renderState(s) {
      const t = s.task || {};
      const ram = s.ramCache || {};
      const totalCtx = num(s.n_ctx, 100096);
      const stage = s.currentStage || 'IDLE';

      const b = document.getElementById('status-badge');
      b.className = s.serverOnline ? 'badge badge-on' : 'badge badge-off';
      b.innerText = s.serverOnline ? (s.is_processing ? 'PROCESSING' : 'IDLE') : 'OFFLINE';
      document.getElementById('overflow-badge').style.display = t.isTruncated ? 'block' : 'none';
      document.getElementById('hdr-ctx').innerText = totalCtx.toLocaleString();

      target.total = totalCtx;
      const inputVal = num(t.totalPrompt, 0);
      // Честная анатомия: в DONE/IDLE бублик и легенда сохраняют состав
      // последнего запроса (reuse/prefill/decode отдельно), без lumping в KV REUSE
      const cachedVal = num(t.kvRestoredTokens, 0);
      const deltaVal = num(t.deltaTokens, 0);
      const genVal = num(t.generatedTokens, 0);

      const rawUsed = cachedVal + deltaVal + genVal;

      if (rawUsed > totalCtx && rawUsed > 0) {
        const scale = totalCtx / rawUsed;
        target.cached = cachedVal * scale;
        target.delta = deltaVal * scale;
        target.gen = genVal * scale;
      } else {
        target.cached = cachedVal;
        target.delta = deltaVal;
        target.gen = genVal;
      }
      // kick только при реальном расхождении: тик P1 вызывает renderState раз в
      // секунду, и безусловный kick крутил бы drawReactor в простое (гейт P5)
      if (Math.abs(anim.cached - target.cached) >= 0.5 ||
          Math.abs(anim.delta  - target.delta)  >= 0.5 ||
          Math.abs(anim.gen    - target.gen)    >= 0.5 ||
          anim.total !== target.total) kick();

      const totalUsed = cachedVal + deltaVal + genVal;
      const usedPct = totalCtx > 0 ? ((totalUsed / totalCtx) * 100).toFixed(1) : '0.0';

      const coreBg = document.getElementById('donut-core-bg');
      const corePhase = document.getElementById('core-phase');
      const coreSpeed = document.getElementById('core-speed');
      
      corePhase.className = 'phase-badge phase-' + stage;

      document.getElementById('row-reuse').classList.toggle('active-row', stage === 'PREFIX' || stage === 'KV_RESTORE');
      document.getElementById('row-prefill').classList.toggle('active-row', stage === 'PREFILL');
      document.getElementById('row-decode').classList.toggle('active-row', stage === 'DECODE');

      if (stage === 'DECODE') {
        coreBg.classList.remove('breathe-idle');
        corePhase.innerText = 'DECODE';
        coreSpeed.innerText = t.decodeTps ? num(t.decodeTps).toFixed(1) + ' t/s' : '...';
        coreSpeed.style.color = 'var(--decode)';
      } else if (stage === 'PREFILL') {
        coreBg.classList.remove('breathe-idle');
        corePhase.innerText = 'PREFILL';
        const prg = t.prefillProgress ? t.prefillProgress + '% ' : '';
        coreSpeed.innerText = prg + (t.prefillTps ? num(t.prefillTps).toFixed(0) + ' t/s' : '...');
        coreSpeed.style.color = 'var(--prefill)';
      } else if (stage === 'PREFIX' || stage === 'KV_RESTORE') {
        coreBg.classList.remove('breathe-idle');
        corePhase.innerText = 'KV REUSE';
        coreSpeed.innerText = cachedVal.toLocaleString() + ' ток';
        coreSpeed.style.color = 'var(--reuse)';
      } else if (stage === 'INPUT') {
        coreBg.classList.remove('breathe-idle');
        corePhase.innerText = 'INPUT';
        coreSpeed.innerText = inputVal.toLocaleString() + ' ток';
        coreSpeed.style.color = 'var(--input)';
      } else if (stage === 'DONE') {
        coreBg.classList.remove('breathe-idle');
        corePhase.innerText = 'DONE ✓';
        coreSpeed.innerText = t.decodeTps ? num(t.decodeTps).toFixed(1) + ' t/s' : '—';
        coreSpeed.style.color = 'var(--reuse)';
      } else {
        coreBg.classList.add('breathe-idle');
        corePhase.innerText = 'IDLE';
        coreSpeed.innerText = '—';
        coreSpeed.style.color = '#fff';
      }

      document.getElementById('core-pct').innerText = 'CONTEXT: ' + totalUsed.toLocaleString() + ' (' + usedPct + '%)';
      document.getElementById('val-input').innerText = inputVal.toLocaleString();
      document.getElementById('val-cached').innerHTML = cachedVal.toLocaleString() + (t.kvSource ? ' <span style="color:var(--dim);font-size:10px">' + t.kvSource.toUpperCase() + '</span>' : '');
      document.getElementById('val-delta').innerText = deltaVal.toLocaleString();
      document.getElementById('val-gen').innerText = genVal.toLocaleString();
      document.getElementById('val-free').innerText = Math.max(0, totalCtx - totalUsed).toLocaleString() + ' ток.';

      const hasSnap = ram.promptCacheMiB != null;
      const ramLimit = ram.limitMiB != null ? num(ram.limitMiB) : 0;
      const cpMib = num(ram.cpUsedMiB, 0);        // живая оценка: сумма активных чекпоинтов
      const promptMib = hasSnap ? num(ram.promptCacheMiB) : 0; // авторитетный снапшот (включает чекпоинты)
      const otherMib = Math.max(0, promptMib - cpMib); // «спящие» ветки вне оценки чекпоинтов
      const cpPct = ramLimit ? (cpMib / ramLimit) * 100 : 0;
      const otherPct = ramLimit ? (otherMib / ramLimit) * 100 : 0;
      document.getElementById('bar-ram-cp').style.width = Math.min(100, cpPct) + '%';
      document.getElementById('bar-ram-prompt').style.width = Math.min(100 - Math.min(100, cpPct), otherPct) + '%';
      document.getElementById('lbl-cp-mib').innerText = cpMib.toLocaleString() + ' MiB';
      document.getElementById('lbl-ram-snap-mib').innerText = hasSnap ? promptMib.toLocaleString() + ' MiB' : 'N/A';
      document.getElementById('lbl-ram-limit').innerText = ram.limitMiB != null ? ramLimit.toLocaleString() : 'N/A';
      const ramGb = ramLimit / 1024;
      document.getElementById('lbl-ram-limit-title').innerText = ram.limitMiB != null ? (Number.isInteger(ramGb) ? ramGb : ramGb.toFixed(1)) + ' GB' : 'N/A';
      document.getElementById('lbl-ram-at').innerText = ram.stateAt ? new Date(ram.stateAt).toLocaleTimeString() : '—';
      document.getElementById('lbl-ram-snap').innerText = ram.usedMiB != null ? num(ram.usedMiB).toLocaleString() + ' MiB / ' + num(ram.promptsCount).toLocaleString() + ' веток' : 'N/A';
      document.getElementById('lbl-cp').innerText = num(ram.cpCurrent, 0) + '/' + (ram.cpMax == null ? '—' : ram.cpMax);
      document.getElementById('lbl-cp-churn').innerText = '+' + num(ram.cpCreated, 0).toLocaleString() + ' / −' + num(ram.cpErased, 0).toLocaleString();

      // Стойка чекпоинтов: ячейки слева→справа = от старых к новым (по n_tokens)
      const cpMax = Math.max(1, ram.cpMax || 32);
      if (cpMax !== renderedCpMax) buildCpGrid(cpMax);
      const nowMs = Date.now() + clockOffset;
      const liveSlots = Object.values(ram.slots || {}).filter(sl => !(sl.evictedAt && nowMs - sl.evictedAt > 2000)).sort((a, b) => a.tokens - b.tokens);
      for (let i = 0; i < renderedCpMax; i++) {
        const cell = document.getElementById('cp-cell-' + i);
        if (!cell) continue;
        const sl = liveSlots[i];
        if (sl) {
          if (sl.evictedAt) {
            cell.style.background = 'rgba(239,68,68,0.55)';
            cell.style.boxShadow = '0 0 6px rgba(239,68,68,0.8)';
            cell.style.opacity = '1';
            cell.title = 'вытеснен · ' + sl.tokens.toLocaleString() + ' tok';
          } else {
            const fresh = sl.lastRestored && (nowMs - sl.lastRestored) < 8000;
            cell.style.background = fresh ? 'rgba(34,197,94,0.55)' : 'rgba(57,201,207,0.30)';
            cell.style.boxShadow = fresh ? '0 0 6px rgba(34,197,94,0.8)' : 'none';
            cell.style.opacity = '1';
            cell.title = sl.tokens.toLocaleString() + ' tok · ' + sl.size.toFixed(1) + ' MiB' + (fresh ? ' · только что поднят из RAM' : '');
          }
        } else {
          cell.style.background = '#0b111a';
          cell.style.boxShadow = 'none';
          cell.style.opacity = '0.35';
          cell.title = '';
        }
      }

      // Лента VRAM: reuse/prefill/decode + проекция чекпоинтов RAM на шкалу токенов
      const tapeTotal = totalCtx;
      const reuseT = Math.min(num(t.kvRestoredTokens, 0), tapeTotal);
      const deltaT = Math.min(num(t.deltaTokens, 0), tapeTotal - reuseT);
      const genT = Math.min(num(t.generatedTokens, 0), tapeTotal - reuseT - deltaT);
      const freeT = Math.max(0, tapeTotal - reuseT - deltaT - genT);
      const setSeg = (id, start, len) => {
        const el = document.getElementById(id);
        el.style.left = (start / tapeTotal * 100) + '%';
        el.style.width = (len / tapeTotal * 100) + '%';
      };
      setSeg('tape-reuse', 0, reuseT);
      setSeg('tape-prefill', reuseT, deltaT);
      setSeg('tape-decode', reuseT + deltaT, genT);
      document.getElementById('lbl-tape-total').innerText = tapeTotal.toLocaleString();
      document.getElementById('lbl-tape-reuse').innerText = reuseT.toLocaleString();
      document.getElementById('lbl-tape-prefill').innerText = deltaT.toLocaleString();
      document.getElementById('lbl-tape-decode').innerText = genT.toLocaleString();
      document.getElementById('lbl-tape-free').innerText = freeT.toLocaleString();
      // Пересобираем DOM только при изменении HTML: тик P1 вызывает renderState
      // раз в секунду, безусловное присваивание мусорило DOM в простое (D6).
      // fresh-подсветка гаснет: при переходе цвет меняется → строка отличается.
      const ticksHtml = Object.values(ram.slots || {})
        .filter(sl => !sl.evictedAt)
        .map(sl => {
          const pct = Math.min(100, sl.tokens / tapeTotal * 100);
          const fresh = sl.lastRestored && (nowMs - sl.lastRestored) < 8000;
          const col = fresh ? '#22c55e' : '#39c9cf';
          return '<div style="position:absolute; top:0; bottom:0; left:' + pct.toFixed(3) + '%; width:3px; background:' + col + ';" title="checkpoint ' + sl.tokens.toLocaleString() + ' tok · ' + sl.size.toFixed(1) + ' MiB"></div>';
        }).join('');
      if (ticksHtml !== lastTicksHtml) {
        lastTicksHtml = ticksHtml;
        document.getElementById('tape-ticks').innerHTML = ticksHtml;
      }

      document.getElementById('lbl-mtp-step').innerText = t.mtpMeanLen ? num(t.mtpMeanLen).toFixed(2) + ' ток/такт' : '— ток/такт';
      const mtpN = s.mtpN || 5;
      if (mtpN !== renderedMtpN) buildMtpBars(mtpN);
      const lblMtpN = document.getElementById('lbl-mtp-n');
      if (lblMtpN) lblMtpN.innerText = String(mtpN);
      const mtp = Array.isArray(t.mtpPosAcc) ? t.mtpPosAcc : [];
      for (let i = 0; i < renderedMtpN; i++) {
        const f = document.getElementById('mtp-f' + i);
        const v = document.getElementById('mtp-v' + i);
        if (f && v) {
          const val = mtp[i];
          if (val == null) {
            f.style.height = '0%';
            v.innerText = '—';
          } else {
            const n = Math.max(0, Math.min(100, num(val, 0)));
            f.style.height = n + '%';
            v.innerText = n + '%';
          }
        }
      }

      const ng = s.ngram || {};
      const lblNg = document.getElementById('lbl-ngram');
      if (lblNg) {
        lblNg.innerText = (ng.accTokens > 0 || ng.genTokens > 0)
          ? num(ng.accTokens).toLocaleString() + '/' + num(ng.genTokens).toLocaleString() + ' ток. (' + (ng.genTokens > 0 ? (num(ng.accTokens) / num(ng.genTokens) * 100).toFixed(1) : '0.0') + '%) | mean ' + num(ng.meanLen).toFixed(2) + ' ток/такт'
          : '—';
      }

      const events = s.events || [];
      const currentEventsHash = events.map(e => (e.id || '') + (e.stage || '')).join('|') + stage;
      if (currentEventsHash !== lastEventsHash) {
        lastEventsHash = currentEventsHash;
        const feed = document.getElementById('log-feed');
        const isPinnedToTop = feed.scrollTop <= 30;
        const oldScrollHeight = feed.scrollHeight;
        const oldScrollTop = feed.scrollTop;
        const groups = {};
        const groupOrder = [];

        for (const ev of events) {
          const tid = ev.taskId || 'SYS';
          if (!groups[tid]) {
            groups[tid] = [];
            groupOrder.push(tid);
          }
          groups[tid].push(ev);
        }

        let html = '';
        for (const tid of groupOrder) {
          const evList = groups[tid];
          const isCurrent = (t.id != null && tid === String(t.id));
          const histItem = (s.history || []).find(h => String(h.id) === String(tid));
          let statusText = 'DONE ✓';
          let statusColor = 'var(--reuse)';
          let summary = '';

          if (isCurrent && s.is_processing) {
            statusText = stage;
            statusColor = (stage === 'DECODE' ? 'var(--decode)' : stage === 'PREFILL' ? 'var(--prefill)' : 'var(--input)');
            summary = 'INPUT: ' + (t.totalPrompt||0).toLocaleString() + ' | GEN: ' + (t.generatedTokens||0).toLocaleString() + ' (' + (t.decodeTps||0) + ' t/s)';
          } else if (histItem) {
            if (histItem.cancelled) {
              statusText = 'CANCELLED ✗';
              statusColor = 'var(--red)';
            } else if (histItem.isTruncated) {
              statusText = 'OVERFLOW ✗';
              statusColor = 'var(--red)';
            } else {
              statusText = 'DONE ✓';
              statusColor = 'var(--reuse)';
            }
            summary = 'INPUT: ' + num(histItem.input).toLocaleString() + ' | REUSE: ' + num(histItem.kvReuse).toLocaleString() + ' | ' + num(histItem.speed).toFixed(1) + ' t/s';
          } else if (tid === 'SYS') {
            statusText = 'SYSTEM';
            statusColor = 'var(--dim)';
            summary = 'Системные события сервера';
          }

          html += '<div class="task-card ' + (isCurrent && s.is_processing ? 'active-task-card' : '') + '" id="task-card-' + esc(tid) + '" data-task-id="' + esc(tid) + '">';
          html += '  <div class="task-card-header" data-task-id="' + esc(tid) + '">';
          html += '    <div class="task-card-title">';
          html += '      <span class="task-badge-id">' + (tid === 'SYS' ? 'SYSTEM' : '#' + esc(tid)) + '</span>';
          html += '      <span class="task-card-summary">' + esc(summary) + '</span>';
          html += '    </div>';
          html += '    <div style="font-weight:bold; color:' + statusColor + ';">' + esc(statusText) + '</div>';
          html += '  </div>';
          html += '  <div class="task-card-body">';

          for (const e of evList) {
            html += '    <div class="log-row ' + esc(e.stage) + '" data-tag="' + esc(e.tag) + '">';
            html += '      <span class="log-time">[' + esc(e.ts) + ']</span>';
            html += '      <span class="tag-pill log-tag">' + esc(e.tag) + '</span>';
            html += '      <span class="log-msg"><b>' + esc(e.title) + ':</b> ' + (e.detail || '') + '</span>';
            html += '    </div>';
          }

          html += '  </div>';
          html += '</div>';
        }

        feed.innerHTML = html;
        if (isPinnedToTop) {
          feed.scrollTop = 0;
        } else {
          feed.scrollTop = oldScrollTop + (feed.scrollHeight - oldScrollHeight);
        }
      }

      const history = s.history || [];
      const currentHistHash = history.map(h => (h.id + h.time + (h.mtpAccepted || '') + (h.mtpMeanLen || '') + (h.cancelled ? 'c' : ''))).join('|');
      if (currentHistHash !== lastHistHash) {
        lastHistHash = currentHistHash;
        document.getElementById('hist-rows').innerHTML = history.map(h => 
          '<tr id="hist-row-' + esc(h.id) + '" data-task-id="' + esc(h.id) + '">' +
          '  <td>' + esc(h.time) + '</td>' +
          '  <td><b style="color:var(--input)">#' + esc(h.id) + '</b></td>' +
          '  <td style="color:var(--input)">' + num(h.input).toLocaleString() + '</td>' +
          '  <td style="color:var(--reuse)">' + num(h.kvReuse).toLocaleString() + (h.kvSource ? ' <span style="color:var(--dim);font-size:10px">' + h.kvSource.toUpperCase() + '</span>' : '') + '</td>' +
          '  <td style="color:var(--prefill)">' + (h.prefillSource === 'estimated' ? '~' : '') + num(h.prefill).toLocaleString() + '</td>' +
          '  <td style="color:var(--decode)">' + num(h.decode).toLocaleString() + '</td>' +
          '  <td style="color:var(--prefix)">' + (h.mtpAccepted != null ? num(h.mtpAccepted).toLocaleString() + '/' + num(h.mtpGenerated).toLocaleString() + ' (' + h.mtpAcceptance + '%) | ' + num(h.mtpMeanLen).toFixed(2) : '—') + '</td>' +
          '  <td><b' + (h.cancelled ? ' style="color:var(--red)"' : '') + '>' + (h.cancelled ? '✗' : num(h.speed).toFixed(1) + ' t/s') + '</b></td>' +
          '</tr>'
        ).join('');
      }
    }

    let sseWorking = false;
    let initialLoadDone = false;
    let latestState = null, renderQueued = false, clockOffset = 0, pollBusy = false;

    function scheduleRender(s) {
      latestState = s;
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(() => {
        renderQueued = false;
        try { if (latestState) renderState(latestState); } catch (err) { console.error(err); }
      });
    }
    function onSnapshot(s) {
      if (s && s.serverNow) clockOffset = s.serverNow - Date.now();
      scheduleRender(s);
    }
    setInterval(() => { if (latestState) scheduleRender(latestState); }, 1000);

    if (window.EventSource) {
      const es = new EventSource('/events');
      es.onopen = () => { sseWorking = true; initialLoadDone = true; };
      es.onmessage = (e) => {
        sseWorking = true;
        initialLoadDone = true;
        try { onSnapshot(JSON.parse(e.data)); } catch (_) {}
      };
      es.onerror = () => { sseWorking = false; };
    }

    async function pollFallback() {
      if (pollBusy || sseWorking) return;
      pollBusy = true;
      try {
        const res = await fetch('/api/state', { cache: 'no-store' });
        if (res.ok) {
          onSnapshot(await res.json());
          initialLoadDone = true;
        } else if (initialLoadDone && !sseWorking) {
          const b = document.getElementById('status-badge');
          b.className = 'badge badge-off';
          b.innerText = 'MONITOR OFFLINE';
        }
      } catch (_) {
        if (initialLoadDone && !sseWorking) {
          const b = document.getElementById('status-badge');
          b.className = 'badge badge-off';
          b.innerText = 'MONITOR OFFLINE';
        }
      } finally {
        pollBusy = false;
      }
    }
    setInterval(pollFallback, 400);
    pollFallback();
  })();
  </script>
</body>
</html>
`;

const server = http.createServer((req, res) => {
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(HTML_PAGE);
  } else if (req.url === '/favicon.ico') {
    res.writeHead(204);
    res.end();
  } else if (req.url === '/events') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'Access-Control-Allow-Origin': '*',
      'X-Accel-Buffering': 'no'
    });
    if (res.flushHeaders) res.flushHeaders();
    if (res.socket && typeof res.socket.setNoDelay === 'function') {
      res.socket.setNoDelay(true);
    }

    const heartbeat = setInterval(() => {
      try {
        res.write(': heartbeat\n\n');
        if (typeof res.flush === 'function') res.flush();
      } catch (_) {
        clearInterval(heartbeat);
        sseClients.delete(res);
      }
    }, 15000);

    res.write(`data: ${snapshotJson()}\n\n`);
    if (typeof res.flush === 'function') res.flush();
    sseClients.add(res);

    req.on('close', () => {
      clearInterval(heartbeat);
      sseClients.delete(res);
    });
  } else if (req.url === '/api/state') {
    res.writeHead(200, { 
      'Content-Type': 'application/json; charset=utf-8', 
      'Cache-Control': 'no-store',
      'Access-Control-Allow-Origin': '*'
    });
    res.end(snapshotJson());
  } else if (req.url === '/api/logs') {
    // Безопасное чтение последних 64 КБ лог-файла (защита от OOM при файлах любого размера)
    fs.stat(LOG_FILE, (err, stats) => {
      if (err || stats.size === 0) {
        res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
        return res.end(`Лог-файл ${LOG_FILE} еще не создан или пуст.\n`);
      }
      const READ_SIZE = Math.min(stats.size, 64 * 1024);
      const buffer = Buffer.alloc(READ_SIZE);
      fs.open(LOG_FILE, 'r', (openErr, fd) => {
        if (openErr) {
          res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end(`Ошибка открытия лог-файла: ${openErr.message}\n`);
        }
        fs.read(fd, buffer, 0, READ_SIZE, stats.size - READ_SIZE, (readErr) => {
          fs.close(fd, () => {});
          if (readErr) {
            res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
            return res.end(`Ошибка чтения: ${readErr.message}\n`);
          }
          const text = buffer.toString('utf8');
          const lines = text.split('\n');
          const cleanLines = lines.slice(1);
          const tail = cleanLines.slice(-150).join('\n');
          res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
          res.end(tail + '\n');
        });
      });
    });
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not found');
  }
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error(`\x1b[1m\x1b[31m❌ ОШИБКА: Порт ${WEB_PORT} уже занят!\x1b[0m`);
    console.error(`Завершите старый процесс: \x1b[33mfuser -k ${WEB_PORT}/tcp\x1b[0m\n`);
  } else {
    console.error(`\x1b[31mОшибка сервера:\x1b[0m`, err);
  }
  process.exit(1);
});

if (REPLAY === -1) {
  server.listen(WEB_PORT, '0.0.0.0', () => {
    console.log(`\x1b[1m\x1b[32m🚀 HARDENED REALTIME PIPELINE MONITOR STARTED:\x1b[0m http://localhost:${WEB_PORT}`);
    console.log(`📡 Connecting to llama-server: ${SERVER_URL}`);
    console.log(`📝 Disk raw log enabled: ${LOG_FILE}\n`);
  });
} else {
  // Только настенные часы: ts/time/stateAt — new Date() (виртуальные часы не
  // покрывают). serverNow в replay не появляется (клиентов нет, flushState
  // выходит до snapshotJson), но остаётся в наборе на случай живых вызовов.
  // lastRestored/evictedAt/_doneSince/_processingStart — Date.now() внутри
  // handleLine → детерминированы виртуальными часами и остаются в снапшоте,
  // чтобы golden-diff видел регрессии в ветках restore/evict.
  const VOLATILE = new Set(['ts', 'time', 'stateAt', 'serverNow']);
  // Виртуальные часы: Date.now() = таймстемп текущей строки лога,
  // иначе sweep evicted-слотов (>2000 мс) зависит от реальной скорости цикла
  const realNow = Date.now;
  let replayTime = 0;
  for (const raw of fs.readFileSync(argv[REPLAY + 1], 'utf8').split('\n')) {
    const m = raw.match(/^\[([^\]]+)\] /);
    if (m) {
      const t = Date.parse(m[1]);
      if (!Number.isNaN(t)) replayTime = t;
    }
    Date.now = () => replayTime;
    handleLine(raw.replace(/^\[[^\]]+\] /, ''));
  }
  Date.now = realNow;
  setTimeout(() => {
    state.events.forEach(e => delete e.id);
    fs.writeFileSync(argv[REPLAY + 2], JSON.stringify(state, (k, v) => VOLATILE.has(k) ? undefined : v, 2));
    process.exit(0);
  }, 2000);
}
