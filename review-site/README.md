# 公开评审展示页

无构建步骤的纯静态只读页面，可作为 ModelScope Static 创空间的页面源。它不调用模型、后端或 ima，不接受账号与密钥，不提供在线生成。

从项目根目录预览：

```sh
python3 -m http.server 8788 --bind 127.0.0.1 --directory review-site
```

打开 `http://127.0.0.1:8788`。不要直接以 `file://` 打开，浏览器会阻止 JSON 的本地 fetch。

`config.json` 由发布者填入真实的 `github`、`modelscope`、`manual` 链接。没有链接时按钮明确显示待发布；不得用假链接代替公开访问验收。提交前应核对 `docs/submission-manifest.json` 和说明书的相同字段。

`assets/` 只含公开成果与策略快照。文章、海报 JSON 均只保留四部分交付内容，清除了内部接口资源 ID、任务 ID 和本机路径。`article-zip.zip` 使用相对图片链接，可独立查看；海报 PDF 是原始单页位图。

需要从已核准的本地运行产物重建公开素材时：

```sh
.venv/bin/python review-site/build_public_assets.py
```

生成器只读取白名单 `output/` 成果及源代码策略，不读取 `data/`、SQLite 或任何凭证。展示页应由发布者保持公开访问，不能以本机服务替代公网可访问页面。

`docs/demo-script.html` 与 `docs/demo-script.md` 按 180 秒安排录制分镜，包含口播、屏幕操作和检查点；它们不是已录制视频，成片导出后仍需核对时长。`docs/manual.pdf` 为作品说明书，由交付流程同步最终 PDF。
