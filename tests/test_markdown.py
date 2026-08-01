from dinbrief.markdown import escape_typst_string, markdown_to_typst


def test_common_inline_markdown_is_preserved() -> None:
    rendered = markdown_to_typst(
        'Text with **bold**, _emphasis_, `code`, and [a link](https://example.com/?q="x").'
    )

    assert "*bold*" in rendered
    assert "_emphasis_" in rendered
    assert "`code`" in rendered
    assert '#link("https://example.com/?q=%22x%22")[a link]' in rendered
    assert escape_typst_string('a"b\\c') == 'a\\"b\\\\c'


def test_ordered_and_nested_lists_keep_their_markers() -> None:
    rendered = markdown_to_typst("3. Third\n4. Fourth\n\n   - Nested")

    assert "3. Third" in rendered
    assert "4. Fourth" in rendered
    assert "  - Nested" in rendered


def test_headings_quotes_and_code_blocks_are_not_dropped() -> None:
    rendered = markdown_to_typst(
        '# Heading\n\n> Quoted text\n\n```text\nvalue = "quoted"\n```'
    )

    assert '#text(weight: "bold")[Heading]' in rendered
    assert "#quote(block: true)[Quoted text" in rendered
    assert '#raw("value = \\"quoted\\"\\n", block: true)' in rendered
