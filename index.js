// dsh-video-kit — 给 DeepSeek Harness 增加原生视频读取能力。
//
// 两个工具：
//   video_read        给本地视频路径或网页链接，返回带时间轴的逐字稿 + 关键帧绝对路径
//   video_kit_setup   体检/安装运行时依赖与 ASR 模型（首次调用 video_read 会自动触发）
//
// 依赖自举：ffmpeg（imageio-ffmpeg 自带二进制）、yt-dlp、sherpa-onnx 与
// Paraformer 中文模型都不随包分发（模型 227 MB，超过包体积上限），
// 首次使用时由 bin/setup.py 下载到数据目录。
//
// 数据目录：$VIDEO_KIT 或 ~/.dsh/toolkits/video-kit（models/、videos/）。

import { execFile } from 'node:child_process'
import { existsSync, readFileSync, readdirSync, mkdirSync, statSync, writeFileSync, copyFileSync } from 'node:fs'
import { join, dirname, basename, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'

const HERE = dirname(fileURLToPath(import.meta.url))
const BIN = join(HERE, 'bin')
const WATCH = join(BIN, 'watch_video.py')
const SETUP = join(BIN, 'setup.py')
const DISCOVER = join(BIN, 'discover.py')
const DATA = process.env.VIDEO_KIT || join(homedir(), '.dsh', 'toolkits', 'video-kit')
const VIDEOS = join(DATA, 'videos')
const ASR_MODEL = join(DATA, 'models', 'asr-paraformer-zh', 'model.int8.onnx')

export const name = 'tool-video-kit'
export const inject = ['tools']

const PY_ENV = { ...process.env, VIDEO_KIT: DATA, PYTHONIOENCODING: 'utf-8' }

function runPython(script, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile('python', [script, ...args], {
      timeout: timeoutMs,
      maxBuffer: 64 * 1024 * 1024,
      windowsHide: true,
      encoding: 'utf8',
      env: PY_ENV,
    }, (err, stdout, stderr) => {
      if (err && !stdout) {
        const tail = String(stderr || '').slice(-2000)
        reject(new Error(`python 执行失败：${err.message}\n${tail}`))
        return
      }
      resolve({ stdout: String(stdout || ''), stderr: String(stderr || ''), code: err ? (err.code ?? 1) : 0 })
    })
  })
}

function parseJsonLine(stdout) {
  const lines = stdout.trim().split(/\r?\n/).reverse()
  for (const line of lines) {
    const s = line.trim()
    if (s.startsWith('{') && s.endsWith('}')) {
      try { return JSON.parse(s) } catch (_) { /* 继续找 */ }
    }
  }
  return null
}

function modelReady() {
  try {
    return existsSync(ASR_MODEL) && statSync(ASR_MODEL).size > 100_000_000
  } catch (_) {
    return false
  }
}

function readTranscript(outdir) {
  const p = join(outdir, 'transcript.txt')
  if (!existsSync(p)) return ''
  return readFileSync(p, 'utf8')
}

function listFrames(outdir) {
  const dir = join(outdir, 'frames')
  if (!existsSync(dir)) return []
  return readdirSync(dir)
    .filter((f) => /^f_\d+\.jpg$/i.test(f))
    .sort()
    .map((f) => join(dir, f))
}

function ensureDirs() {
  try {
    mkdirSync(VIDEOS, { recursive: true })
    mkdirSync(join(DATA, 'models'), { recursive: true })
  } catch (_) { /* 目录创建失败会在执行阶段暴露 */ }
}

// 缺模型才自举，避免每次调用都跑 pip 检查
async function bootstrapIfNeeded(timeoutMs) {
  if (modelReady()) return { bootstrapped: false }
  if (!existsSync(SETUP)) {
    throw new Error(`video_read: 找不到自举脚本 ${SETUP}（包被裁剪？请重新安装 dsh-video-kit）`)
  }
  const { stdout, stderr } = await runPython(SETUP, [], timeoutMs)
  const state = parseJsonLine(stdout)
  if (!state || !state.ok) {
    throw new Error('video_read: 运行时依赖未就绪，自举未成功。\n'
      + (state ? JSON.stringify(state) : (stdout + stderr).slice(-1500))
      + '\n可手动执行：python "' + SETUP + '"')
  }
  return { bootstrapped: true, log: stderr.trim().slice(-800) }
}

function registerTools(ctx) {
  ctx.tools.register({
    name: 'video_read',
    description:
      '读取一个视频：给本地文件绝对路径或网页链接（B站/腾讯/YouTube 等），返回带时间轴的逐字稿、'
      + '关键帧图片的绝对路径（可用 read_image 逐帧查看）以及输出目录。'
      + '首次使用会自动下载 ffmpeg 与语音识别模型（约 290 MB，可能耗时数分钟）。'
      + '长视频处理较慢（约每 10 分钟视频 1–2 分钟），可用 timeoutMs 放宽。',
    parameters: {
      type: 'object',
      properties: {
        source: { type: 'string', description: '本地视频绝对路径，或网页视频链接。' },
        every: { type: 'number', description: '每隔多少秒抽一张关键帧，默认 20；短视频会自动加密抽帧。' },
        maxframes: { type: 'number', description: '最多抽多少张关键帧，默认 24。' },
        timeoutMs: { type: 'number', description: '整体超时（毫秒），默认 900000（15 分钟）。' },
        copyTo: { type: 'string', description: '可选：把关键帧与逐字稿复制到这个目录（建议传当前工作区内的绝对路径），用于沙箱受限的会话里直接看图。' },
      },
      required: ['source'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          outdir: { type: 'string' },
          transcript: { type: 'string' },
          frames: { type: 'array', items: { type: 'string' } },
          duration: { type: 'string' },
          log: { type: 'string' },
        },
        required: ['outdir', 'transcript', 'frames'],
      },
      render: (_args, v) => {
        const head = `视频读取完成｜逐字稿 ${v.transcript.length} 字｜关键帧 ${v.frames.length} 张\n输出目录：${v.outdir}`
        const body = v.transcript ? `\n\n${v.transcript.slice(0, 3000)}` : '\n\n（无语音内容或识别为空）'
        const more = v.transcript.length > 3000 ? '\n…（完整内容见 transcript.txt）' : ''
        return [{ type: 'text', text: head + body + more }]
      },
    },
    async execute(args) {
      if (typeof args.source !== 'string' || args.source.trim() === '') {
        throw new Error('video_read: source 不能为空')
      }
      if (!existsSync(WATCH)) {
        throw new Error(`video_read: 缺少运行时脚本 ${WATCH}，请重新安装 dsh-video-kit`)
      }
      ensureDirs()
      const src = args.source.trim()
      const isWinPath = /^[A-Za-z]:[\\/]/.test(src) || src.startsWith('\\\\')
      if (isWinPath) {
        if (!existsSync(src)) {
          const dir = dirname(src)
          let hint = ''
          if (existsSync(dir)) {
            const base = basename(src, extname(src)).toLowerCase()
            const all = readdirSync(dir)
            const same = all.filter((f) => basename(f, extname(f)).toLowerCase() === base)
            const vids = all.filter((f) => /\.(mp4|mov|mkv|flv|webm|m4v)$/i.test(f))
            if (same.length) hint += `\n同名不同扩展名：${same.join(', ')}`
            if (vids.length) hint += `\n该目录下的视频（前10个）：\n${vids.slice(0, 10).map((f) => '  ' + join(dir, f)).join('\n')}`
          }
          throw new Error(`video_read: 本地文件不存在 —— ${src}`
            + `\n请确认 source 指向【视频文件本身】（不能是目录），且路径正确。${hint}`)
        }
      } else if (!/^https?:\/\//i.test(src)) {
        throw new Error(`video_read: source 既不是本地绝对路径也不是 http(s) 链接 —— ${src}`)
      }

      const timeoutMs = typeof args.timeoutMs === 'number' && args.timeoutMs > 0 ? args.timeoutMs : 900000
      const copyTo = typeof args.copyTo === 'string' && args.copyTo.trim() ? args.copyTo.trim() : ''
      let bootLog = ''
      if (!modelReady()) {
        const boot = await bootstrapIfNeeded(Math.max(timeoutMs, 1800000))
        bootLog = boot.log || ''
      }

      let everyGap = typeof args.every === 'number' && args.every > 0 ? args.every : 20
      const maxframes = typeof args.maxframes === 'number' && args.maxframes > 0 ? args.maxframes : 24
      // 短视频自动加密抽帧：时长未知时先按 2 秒试，若只剩 1 帧下面会重跑
      const isShortHint = /\.(mp4|mov|webm)$/i.test(src) && everyGap === 20
      if (isShortHint) everyGap = 2

      let { stdout, stderr } = await runPython(WATCH, [src, '--every', String(everyGap), '--maxframes', String(maxframes)], timeoutMs)
      let outdirLine = /OUTDIR:\s*(.+)$/m.exec(stdout)
      if (!outdirLine) {
        throw new Error(`video_read: 未拿到输出目录。原始输出：\n${stdout.slice(-2000)}\n${stderr.slice(-1000)}`)
      }
      let outdir = outdirLine[1].trim()
      let frames = listFrames(outdir)
      if (frames.length < 2 && everyGap > 1) {
        const retry = await runPython(WATCH, [src, '--every', '2', '--maxframes', String(maxframes)], timeoutMs)
        if (/OUTDIR:\s*(.+)$/m.test(retry.stdout)) {
          stdout = retry.stdout
          stderr = retry.stderr
          outdir = /OUTDIR:\s*(.+)$/m.exec(stdout)[1].trim()
          frames = listFrames(outdir)
        }
      }

      const videoLine = /VIDEO:\s*(.+?)\s+dur=([\d.]+)s/m.exec(stdout)
      const log = [bootLog, stderr.trim().slice(-500)].filter(Boolean).join('\n')
      let transcript = readTranscript(outdir)
      let outFrames = frames
      if (copyTo) {
        try {
          const dst = join(copyTo, outdir.split(/[\\/]/).pop())
          mkdirSync(dst, { recursive: true })
          outFrames = frames.map((f) => {
            const target = join(dst, f.split(/[\\/]/).pop())
            copyFileSync(f, target)
            return target
          })
          if (transcript) writeFileSync(join(dst, 'transcript.txt'), transcript, 'utf8')
        } catch (_) { /* 复制失败不影响主流程 */ }
      }
      return {
        outdir,
        transcript,
        frames: outFrames,
        duration: videoLine ? `${videoLine[2]}s` : '',
        log,
      }
    },
    presentCall: (args) => ({ card: 'generic', title: `读取视频 ${args.source}` }),
  })

  // 发现层：接管一个你自己登录过的浏览器窗口去搜索，再把 URL 交给 video_read
  ctx.tools.register({
    name: 'video_discover',
    description:
      '按关键词在需要登录态的站点上找视频候选（抖音 / 小红书 / 公众号 / B站），只读列表页、不下载。'
      + '工作方式：接管本机一个**你自己登录过**的 Edge 窗口（插件自己的 profile 目录，不接触账号密码）。'
      + '首次使用某平台：action=login 打开窗口让你登录 → action=status 确认 loggedIn=true → action=search 检索。'
      + '拿到的 items[].url 直接传给 video_read 即可抽帧与转写。'
      + '未登录时不会崩溃，会返回 loggedIn=false 与 warning。',
    parameters: {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['status', 'login', 'search'],
          description: 'status=查看各平台登录态；login=打开窗口等你登录；search=按关键词检索。',
        },
        platform: {
          type: 'string',
          enum: ['douyin', 'xhs', 'weixin', 'bilibili'],
          description: '目标平台，默认 douyin。bilibili 不需要登录，可用来验证链路。',
        },
        query: { type: 'string', description: '检索关键词（action=search 必填）。' },
        limit: { type: 'number', description: '最多返回几条候选，默认 10。' },
        settle: { type: 'number', description: '页面加载等待秒数，默认 5；结果为空可调到 8。' },
      },
      required: ['action'],
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          action: { type: 'string' },
          platform: { type: 'string' },
          loggedIn: { type: 'boolean' },
          count: { type: 'number' },
          items: { type: 'array', items: { type: 'object', additionalProperties: true } },
          hint: { type: 'string' },
          warning: { type: 'string' },
          searchUrl: { type: 'string' },
          detail: { type: 'string' },
        },
        required: ['ok', 'action'],
      },
      render: (_a, v) => {
        const lines = [`video_discover ${v.action}${v.platform ? ' / ' + v.platform : ''} → ${v.ok ? 'ok' : 'failed'}`]
        if (v.loggedIn !== undefined) lines.push(`登录态：${v.loggedIn ? '已登录' : '未登录'}`)
        if (v.count !== undefined) lines.push(`候选：${v.count} 条`)
        if (v.detail) lines.push(v.detail)
        if (v.hint) lines.push(`提示：${v.hint}`)
        if (v.warning) lines.push(`注意：${v.warning}`)
        for (const [i, it] of (v.items || []).entries()) {
          lines.push(`${i + 1}. ${it.title || '(无标题)'}\n   ${it.url}`)
        }
        return [{ type: 'text', text: lines.join('\n') }]
      },
    },
    async execute(args) {
      const action = String(args.action || 'status')
      const platform = String(args.platform || 'douyin')
      const cli = [action]
      if (action === 'login') cli.push(platform)
      if (action === 'search') {
        if (!args.query) throw new Error('action=search 需要 query')
        cli.push(platform, String(args.query))
        if (args.limit != null) cli.push('--limit', String(args.limit))
        if (args.settle != null) cli.push('--settle', String(args.settle))
      }
      const { stdout } = await runPython(DISCOVER, cli, action === 'search' ? 180000 : 90000)
      const v = parseJsonLine(stdout)
      if (!v) throw new Error('discover.py 没有返回 JSON：' + String(stdout).slice(-500))
      const out = { ok: v.ok !== false, action }
      for (const k of ['platform', 'loggedIn', 'count', 'items', 'hint', 'warning', 'searchUrl']) {
        if (v[k] !== undefined && v[k] !== null) out[k] = v[k]
      }
      if (v.platforms) {
        out.detail = Object.entries(v.platforms)
          .map(([k, p]) => `${k}: ${p.loggedIn === null ? '无需登录' : (p.loggedIn ? '已登录' : '未登录')}`)
          .join(' | ')
      }
      return out
    },
    presentCall: (args) => ({ card: 'generic', title: `检索候选 ${args.platform || 'douyin'} ${args.query || ''}` }),
  })

  ctx.tools.register({
    name: 'video_kit_setup',
    description:
      '体检或安装 video_read 的运行时依赖：python 包（imageio-ffmpeg / yt-dlp / sherpa-onnx / websocket-client）'
      + '与中文语音识别模型（Paraformer + Silero VAD，约 290 MB）。'
      + 'check=true 只体检不改动；默认按需安装，幂等。',
    parameters: {
      type: 'object',
      properties: {
        check: { type: 'boolean', description: '只检查状态，不下载安装，默认 false。' },
      },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean' },
          dataDir: { type: 'string' },
          deps: { type: 'string' },
          models: { type: 'string' },
          detail: { type: 'string' },
        },
        required: ['ok', 'dataDir'],
      },
      render: (_a, v) => [{
        type: 'text',
        text: `video-kit ${v.ok ? '已就绪' : '未就绪'}\n数据目录：${v.dataDir}\n依赖：${v.deps}\n模型：${v.models}${v.detail ? '\n' + v.detail : ''}`,
      }],
    },
    async execute(args) {
      ensureDirs()
      const checkOnly = args && args.check === true
      const { stdout, stderr } = await runPython(SETUP, checkOnly ? ['--check'] : [], 1800000)
      const state = parseJsonLine(stdout)
      if (!state) throw new Error('video_kit_setup: 无法解析 setup.py 输出\n' + (stdout + stderr).slice(-1500))
      return {
        ok: !!state.ok,
        dataDir: state.data_dir || DATA,
        deps: Object.entries(state.deps || {}).map(([k, v]) => `${k}=${v ? 'ok' : 'missing'}`).join(', '),
        models: Object.entries(state.models || {}).map(([k, v]) => `${k}=${v ? 'ok' : 'missing'}`).join(', '),
        detail: state.error || '',
      }
    },
    presentCall: () => ({ card: 'generic', title: '检查 video-kit 运行环境' }),
  })
}

export function apply(ctx) {
  ensureDirs()
  try {
    registerTools(ctx)
  } catch (err) {
    try {
      writeFileSync(join(DATA, 'register-error.txt'),
        `${new Date().toISOString()}\n${err && err.stack ? err.stack : String(err)}\n`, 'utf8')
    } catch (_) { /* 忽略 */ }
    throw err
  }
}
