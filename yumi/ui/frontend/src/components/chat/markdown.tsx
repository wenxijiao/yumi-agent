import { memo } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"

/** Renders assistant markdown with GitHub-flavored extensions + code highlighting. */
export const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="prose-yumi text-[15px]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          a: ({ node: _n, ...props }) => <a target="_blank" rel="noreferrer noopener" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})
