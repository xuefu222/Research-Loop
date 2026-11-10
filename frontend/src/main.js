import { createApp, ref, onMounted, onUnmounted } from 'vue/dist/vue.esm-bundler.js'
import './style.css'

createApp({
  setup() {
    const documents = ref([]), selected = ref([]), scope = ref('full'), mode = ref('agent')
    const questions = ref('QASPER 包含多少个问题，涉及多少篇论文？')
    const report = ref(null), packet = ref(null), trace = ref([]), metrics = ref(null)
    const error = ref(''), busy = ref(false), health = ref(null), taskId = ref(''), status = ref('ready')
    const upload = ref(null), uploadTitle = ref(''), importing = ref(false)
    let connection
    async function api(path, options) {
      const response = await fetch(path, options)
      if (!response.ok) {
        let message = '请求失败 ' + response.status
        try { const body = await response.json(); message = JSON.stringify(body.detail || body) } catch {}
        throw new Error(message)
      }
      return response.json()
    }
    async function refresh() {
      const data = await api('/api/documents')
      documents.value = data.documents
      if (!selected.value.length) selected.value = data.documents.map(d => d.doc_id)
      health.value = await api('/api/health')
    }
    async function finish() {
      const data = await api('/api/tasks/' + taskId.value)
      status.value = data.status
      if (data.status === 'failed' || data.status === 'interrupted') error.value = data.error
      if (data.status === 'completed') {
        report.value = data.result.report
        packet.value = data.result.packet
        metrics.value = data.result.metrics
      }
      if (['completed', 'failed', 'interrupted'].includes(data.status)) {
        busy.value = false
        connection?.close()
      }
    }
    async function run() {
      error.value = ''; report.value = null; packet.value = null; trace.value = []; metrics.value = null
      if (!questions.value.trim() || !selected.value.length) { error.value = '请输入问题并选择至少一篇论文'; return }
      busy.value = true; status.value = 'queued'
      try {
        const data = await api('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ questions: questions.value.split('\n').map(q => q.trim()).filter(Boolean),
            doc_ids: selected.value, scope: scope.value, mode: mode.value }) })
        taskId.value = data.task_id
        connection?.close()
        connection = new EventSource('/api/tasks/' + taskId.value + '/events')
        connection.onmessage = async (event) => {
          const detail = JSON.parse(event.data)
          if (!trace.value.some(e => e.sequence === detail.sequence)) trace.value.push(detail)
          status.value = detail.node
          if (['completed', 'failed'].includes(detail.status)) {
            try { await finish() } catch (e) { error.value = e.message; busy.value = false; connection.close() }
          }
        }
        connection.onerror = () => { status.value = 'reconnecting' }
      } catch (e) { error.value = e.message; busy.value = false }
    }
    async function importPdf() {
      const file = upload.value?.files?.[0]
      if (!file) return
      importing.value = true; error.value = ''
      try {
        const form = new FormData(); form.append('file', file); form.append('title', uploadTitle.value)
        const task = await api('/api/documents', { method: 'POST', body: form })
        let result
        do { await new Promise(r => setTimeout(r, 1200)); result = await api('/api/tasks/' + task.task_id) }
        while (['queued', 'running'].includes(result.status))
        if (result.status !== 'completed') throw new Error(result.error)
        await refresh(); selected.value = [...new Set([...selected.value, task.doc_id])]
        uploadTitle.value = ''; upload.value.value = ''
      } catch(e) { error.value = e.message } finally { importing.value = false }
    }
    function sample(kind) {
      scope.value = kind === 'scope' ? 'abstract' : 'full'
      selected.value = kind === 'compare' ? ['rag', 'selfrag'] : ['qasper']
      questions.value = kind === 'scope' ? 'QASPER 包含多少个问题，涉及多少篇论文？\n仅依据摘要，能否确认作者使用的 GPU 型号？'
        : kind === 'compare' ? '比较这两篇论文：RAG 采用的生成模型是什么，Self-RAG 用于自我反思的特殊 token 是什么？'
        : 'QASPER 包含多少个问题，涉及多少篇论文？'
    }
    onMounted(() => refresh().catch(e => error.value = e.message))
    onUnmounted(() => connection?.close())
    return { documents, selected, scope, mode, questions, report, packet, trace, metrics, error,
      busy, health, taskId, status, run, sample, upload, uploadTitle, importing, importPdf }
  },
  template: `
  <div class="shell">
    <header><div class="brand"><span class="mark">P</span><div>Paper Research<small>论文调研与证据核验</small></div></div>
      <div class="health"><span :class="['dot', health?.model_configured ? 'green' : '']"></span>{{ health?.model_configured ? '模型接口已配置' : '正在检查接口' }}</div></header>
    <section class="intro"><span class="eyebrow">RESEARCH WITH EVIDENCE</span><h1>让每个结论，都有原文可查。</h1>
      <p>选择论文与材料范围，提交研究问题。检索、生成和核验的过程都保留记录。</p></section>
    <main><aside><h2>研究材料 <span>{{ documents.length }}</span></h2>
      <label class="paper" v-for="doc in documents" :key="doc.doc_id"><input type="checkbox" :value="doc.doc_id" v-model="selected">
        <div><strong>{{ doc.title }}</strong><small>{{ doc.page_count }} 页 · {{ doc.abstract_chunks }} 个摘要片段</small></div></label>
      <div class="field"><label>材料范围</label><select v-model="scope"><option value="full">已索引全文</option><option value="abstract">仅摘要</option></select></div>
      <div class="field"><label>执行方式</label><select v-model="mode"><option value="agent">生成并审核报告</option><option value="packet">只整理候选证据</option></select></div>
      <details class="import"><summary>导入自己的论文</summary><input ref="upload" type="file" accept=".pdf,application/pdf">
        <input v-model="uploadTitle" placeholder="论文标题（可选）"><button class="secondary" @click="importPdf" :disabled="importing">{{ importing ? '正在入库…' : '上传并建立索引' }}</button></details>
    </aside><div class="workspace"><section class="card question"><h2>你的研究问题</h2>
      <textarea v-model="questions" rows="4" placeholder="每行一个问题，最多 5 个"></textarea>
      <div class="examples"><button @click="sample('basic')">数据集规模</button><button @click="sample('scope')">摘要边界测试</button><button @click="sample('compare')">跨论文比较</button></div>
      <div class="action"><small>BM25 + 语义检索 · RRF 融合 · 原文核验</small><button class="primary" @click="run" :disabled="busy">{{ busy ? '研究进行中…' : '开始调研 →' }}</button></div></section>
      <p class="error" v-if="error">{{ error }}</p>
      <section class="card activity" v-if="trace.length || busy"><div class="row"><h2>执行记录</h2><span class="badge">{{ status }}</span></div>
        <div class="steps"><span v-for="item in trace" :key="item.sequence">{{ item.node }}<small v-if="item.elapsed_seconds !== undefined">{{ item.elapsed_seconds }}s</small></span></div>
        <small v-if="metrics">检索 {{ metrics.attempts }} 轮 · 模型调用 {{ metrics.model_calls.length }} 次 · 总耗时 {{ metrics.elapsed_seconds }} 秒</small></section>
      <section class="card results" v-if="report"><div class="row"><h2>调研结果</h2><nav><a :href="'/api/tasks/'+taskId+'/report?format=md'">下载 Markdown</a><a :href="'/api/tasks/'+taskId+'/report?format=json'">下载 JSON</a></nav></div>
        <p class="scope">{{ report.material_scope }}</p>
        <article v-for="(answer, index) in report.answers" :key="index"><div class="row"><h3>{{ answer.question }}</h3><span :class="['badge', answer.status]">{{ answer.status }}</span></div>
          <p class="answer">{{ answer.answer }}</p><small>关联证据：{{ answer.evidence_ids.join(', ') || '暂无' }}</small></article>
        <h3>原文证据</h3><details class="evidence" v-for="item in report.evidence" :key="item.evidence_id" open>
          <summary>{{ item.evidence_id }} · {{ item.source_id }} · PDF 第 {{ item.pdf_page }} 页</summary><blockquote>{{ item.text }}</blockquote><small>{{ item.location }}</small></details>
        <details class="limits"><summary>材料与核验限制</summary><p v-for="(limit,i) in report.limitations" :key="i">{{ limit }}</p></details></section>
      <section class="card" v-else-if="packet"><h2>候选证据包</h2><p>尚未生成回答，可交给 Codex 中的 Skill 继续核验。</p>
        <details class="evidence" v-for="item in packet.chunks" :key="item.chunk_id"><summary>{{ item.doc_id }} · 第 {{ item.pdf_page }} 页</summary><blockquote>{{ item.raw_text }}</blockquote></details></section>
      <section class="empty" v-if="!report && !packet && !busy"><div>↗</div><h3>从一个需要证据的问题开始</h3><p>先试试“摘要边界测试”，观察系统如何区分可确认与信息不足。</p></section>
    </div></main><footer>本地论文工作台 · PDF 页码以文件顺序为准 · 自动审核不能代替人工阅读</footer>
  </div>`
}).mount('#app')
