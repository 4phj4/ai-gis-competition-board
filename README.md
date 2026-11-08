# AI × GIS 竞赛与项目机会看板

本工程实现公开赛事公告的保守采集、历史对比和响应式网页。卡片里的信息来自官方页面；抓不到的字段显示“未公布／待核实”。页面无 AI 接口、账号、推送或付费依赖。

## 本地运行

```powershell
python -m pip install -r requirements.txt
python collect.py
python -m http.server 8000 --directory dist
```

浏览器打开 `http://localhost:8000`。必须通过 HTTP 打开，直接双击 HTML 会阻止读取 `data.json`。

## 数据与判断

- `sources.json` 列出原有 18 个来源及 2026-11-08 追加的 12 个具体入口。网页区分“列表采集”和“单页监测”：前者能发现新机会，后者只监测一场已知赛事的变化。`pending` 和 `blocked` 会显示具体原因。
- `data/state.json` 是持久化历史。云端运行时应提交到私有或公开仓库，不能丢弃。`dist/data.json` 是公开网页数据，不含凭据。
- 每个来源首次接入时发现的旧公告标记 `baseline`，不算“今日新增”。此后新 URL 算新增；同 URL 正文指纹变化算变更。不同届次必须有不同 URL 才能独立保留，名称相同不自动合并。
- 卡片区分竞赛、校内选拔和项目申报；校内公告优先显示单独的“本校截止”，仅从明确的截止语句提取。学校认可度以本校当年竞赛目录为准，不按来源直接推断。
- 本版只从明确的“报名截止”“作品提交截止”语句提取日期。没有官方原文证据时不推断资格、队伍人数或专业限制。
- 本版只读取少量官方网页，未实现所有来源自动化。来源状态是一次运行的结果，不代表永久可用。

## 云端运行状态

在线地址：https://4phj4.github.io/ai-gis-competition-board/

公开仓库：https://github.com/4phj4/ai-gis-competition-board

`.github/workflows/update.yml` 已在 GitHub Actions 启用北京时间每天 08:00 的定时采集、历史提交和 Pages 部署，也可手动触发。仓库变量 `PUBLIC_SITE=true` 已设置，Pages 来源为 GitHub Actions。2026-10-12 至 10-15 的自然定时运行均成功，但实际触发晚于 08:00；最近状态以 Actions 运行记录和网页的“最近成功更新”时间为准。

GitHub Pages 网页和仓库均公开，任何持链接者都可访问。云端调度可能延迟，不能保证分秒准确；公开仓库长时间无活动也可能被停用定时工作流。

页面会区分“最近成功更新”和本轮来源错误；单个来源失败不会清除旧卡片。详情准确性始终以官方当届通知为准。
