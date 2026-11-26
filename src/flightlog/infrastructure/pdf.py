"""PdfRenderer with Playwright: headless Chromium prints the report's HTML (ADR-0006, 0016)."""

import html

from playwright.sync_api import Route, sync_playwright

# Chromium fills .pageNumber and .totalPages. The footer has no page styles of its own, so its
# font size must be set here or it renders at a few pixels.
_FOOTER = (
    '<div style="width:100%;font:8px sans-serif;color:#555;text-align:center">'
    '{text} · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>'
)


class ChromiumPdfRenderer:
    """One browser per render, closed afterwards: a report is a rare, short job."""

    def render(self, html_page: str, footer: str) -> bytes:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                # The report needs no JavaScript and nothing from the network. Turning both off
                # means a path or branch name that slipped past escaping still can't run or call.
                page = browser.new_page(java_script_enabled=False)
                page.route("**/*", _block)
                page.set_content(html_page, wait_until="load")
                return page.pdf(
                    format="A4",
                    margin={"top": "15mm", "right": "15mm", "bottom": "18mm", "left": "15mm"},
                    print_background=True,
                    display_header_footer=True,
                    header_template="<span></span>",  # an empty header, not Chromium's default
                    footer_template=_FOOTER.format(text=html.escape(footer)),
                    tagged=True,  # structure for screen readers
                    outline=True,  # bookmarks from the headings: one per repo
                )
            finally:
                browser.close()


def _block(route: Route) -> None:
    route.abort()
