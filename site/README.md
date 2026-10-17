# 回放电台 · 官网单页

以 maa.plus 的视觉语言与信息架构为参照做的单页官网，适配「回放电台」自身的信息。
**是设计思路借鉴，不是像素级拷贝**：没有使用对方的代码、Logo、插画或文案。

线上地址：<https://dcc176.github.io/replay-radio/>

## 部署

线上由 **GitHub Pages 的 `gh-pages` 分支**发布（仓库 Settings → Pages → Deploy from a branch：`gh-pages` / `/`）。
`site/` 是唯一源文件，`gh-pages` 只是产物，**不要直接改那个分支**。

发布一次（把 `site/` 的树作为一条根提交推上去，无需切换分支、无需额外依赖）：

```bash
tree=$(git rev-parse HEAD:site)
commit=$(git commit-tree "$tree" -m "site: publish $(git rev-parse --short HEAD)")
git push origin "$commit:refs/heads/gh-pages"
```

> **想升级成 push 即发布的 Actions 流水线**（不用手动跑上面两行）：
> 1. `gh auth refresh -s workflow` 给 gh 令牌补上 `workflow` 权限（当前只有 `repo`，GitHub 会拒收 workflow 文件）；
> 2. 把下面这个文件加到 `.github/workflows/pages.yml`；
> 3. 仓库 Settings → Pages → Source 改成 **GitHub Actions**。
>
> ```yaml
> name: Deploy site to GitHub Pages
> on:
>   push:
>     branches: [main]
>     paths: ["site/**", ".github/workflows/pages.yml"]
>   workflow_dispatch:
> permissions:
>   contents: read
>   pages: write
>   id-token: write
> concurrency:
>   group: pages
>   cancel-in-progress: true
> jobs:
>   deploy:
>     runs-on: ubuntu-latest
>     environment:
>       name: github-pages
>       url: ${{ steps.deployment.outputs.page_url }}
>     steps:
>       - uses: actions/checkout@v7
>       - uses: actions/configure-pages@v6
>       - uses: actions/upload-pages-artifact@v5
>         with:
>           path: site
>       - id: deployment
>         uses: actions/deploy-pages@v5
> ```

## 本地预览

```bash
python -m http.server 8791 --bind 127.0.0.1 --directory site
# 打开 http://127.0.0.1:8791/
```

直接双击 `index.html` 也能看，但 `file://` 下浏览器会拦截跨域请求，
版本号与测速会停在回退值（不影响版面）。

## 结构

```
site/
  index.html   单文件页面：内联 CSS + JS，无构建链、无第三方依赖
  assets/      五张实机截图（1440×860，WebP，合计约 400 KB）
```

## 页面里哪些是「活」的

| 能力 | 实现 | 说明 |
|---|---|---|
| 版本号 / 安装包名 / 体积 | `GET api.github.com/repos/DcC176/replay-radio/releases/latest` | 失败时回退到常量 `FALLBACK`，不报错 |
| 平台与架构检测 | `navigator.userAgentData.platform` + UA 兜底 | 非 Windows 显示「暂无打包版」并切到对应页签 |
| 连通性测速 | 接口用 CORS GET，Release 页用 `no-cors` HEAD | 量的是接口往返耗时，不是下载速度 |
| 深浅主题 | `data-theme` + localStorage | 默认深色，与桌面端一致 |
| 滚动入场 / 光斑 / 聚光 | IntersectionObserver + CSS keyframes | `prefers-reduced-motion` 下全部关闭 |

## 更新截图

截图取自本机运行中的实例（1440×860 视口，无头 Chrome 直接抓，不做后期）。
换图时保持 1440×860，同名覆盖 `assets/` 下对应文件即可，页面用 `width/height` 占位，不会跳版。

## 已知限制

- 打包版只有 Windows x64，macOS / Linux 页签显示「暂未提供」，属真实状态。
- 测速结果受本机网络与代理影响，不同时段差异可能很大。
- 未做 i18n，按中文单语处理。

## 版权

maa.plus 的网站仓库 `MaaAssistantArknights/maa-website` 未声明任何开源许可（默认版权保留），
因此本页面只复刻布局与交互模式，代码与素材均为重写。截图中的主播名与头像是其公开页面内容，
如需撤下请提 Issue。
