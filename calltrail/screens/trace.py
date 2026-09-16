"""Interactive static graph navigation; all indexing and reads run off the UI loop."""
from __future__ import annotations

import asyncio

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from calltrail.trace.graph import CallHierarchy
from calltrail.trace.models import SymbolLocation, TraceProvider
from calltrail.trace.presentation import DISCLAIMER, format_trace, trace_data


class TraceScreen(ModalScreen[None]):
    BINDINGS = [Binding('escape', 'back', 'Back'), Binding('b', 'back', 'Back', show=False),
                Binding('q', 'dismiss', 'Close'), Binding('i', 'incoming', 'Callers'),
                Binding('o', 'outgoing', 'Callees'), Binding('e', 'entries', 'Entry paths'),
                Binding('r', 'refresh_trace', 'Refresh'), Binding('/', 'search', 'Find')]
    DEFAULT_CSS = """
    TraceScreen { align: center middle; background: #101010 85%; }
    #trace-dialog { width: 95%; max-width: 120; height: 90%; border: solid #505050;
                    background: #101010; color: #d4d4d4; padding: 1 2; }
    #trace-title, #trace-status, #trace-breadcrumb { height: auto; }
    #trace-query { height: 3; background: #101010; color: #d4d4d4; }
    #trace-list { height: 1fr; min-height: 3; background: #101010; color: #d4d4d4; }
    #trace-detail { height: 1fr; min-height: 4; background: #101010; }
    """

    def __init__(self, provider: TraceProvider):
        super().__init__()
        self.provider = provider
        self.target = ''
        self.mode = 'incoming'
        self.history: list[tuple[str, str]] = []
        self.graph: CallHierarchy | None = None
        self.data: dict | None = None
        self._options: list[tuple[str, str]] = []
        self._generation = 0

    def compose(self) -> ComposeResult:
        with Vertical(id='trace-dialog'):
            yield Static('Trace · Enter select · i callers · o callees · e entry paths · b/Esc back · / find · r refresh',
                         id='trace-title', markup=False)
            yield Input(placeholder='Symbol, Class.method, or file.py:line; Enter to find', id='trace-query')
            yield Static(DISCLAIMER, id='trace-status', markup=False)
            yield Static('', id='trace-breadcrumb', markup=False)
            yield OptionList(id='trace-list')
            yield RichLog(id='trace-detail', markup=False, wrap=True, max_lines=1000)

    def on_mount(self):
        self.query_one(Input).focus()
        self.action_refresh_trace()

    @work(group='trace-index', exclusive=True, exit_on_error=False)
    async def action_refresh_trace(self):
        self.query_one('#trace-status', Static).update('Indexing Python symbols...')
        try:
            index = await asyncio.to_thread(self.provider.refresh)
            self.graph = await asyncio.to_thread(CallHierarchy, self.provider.root, index)
            self.query_one('#trace-status', Static).update(
                f'{index.files_indexed} files · {len(index.symbols)} symbols · {len(index.warnings)} warnings · {DISCLAIMER}')
            if self.target:
                self.show_target()
        except Exception as exc:
            self.query_one('#trace-status', Static).update(f'Trace indexing unavailable: {type(exc).__name__}')

    def on_input_submitted(self, event: Input.Submitted):
        self.navigate(event.value.strip())
        event.stop()

    def navigate(self, target: str, mode: str | None = None):
        if not target:
            return
        if self.target:
            self.history.append((self.target, self.mode))
            self.history = self.history[-100:]
        self.target = target
        if mode:
            self.mode = mode
        self.query_one(OptionList).focus()
        self.show_target()

    @work(group='trace-query', exclusive=True, exit_on_error=False)
    async def show_target(self):
        if not self.graph:
            return
        self._generation += 1
        generation = self._generation
        options = self.query_one(OptionList)
        options.clear_options()
        self._options = []
        target, mode, graph = self.target, self.mode, self.graph
        try:
            data = await asyncio.to_thread(trace_data, graph, target,
                                           outgoing=mode == 'outgoing', to_entry=mode == 'entries', max_relations=200)
            preview = []
            if data['symbol']:
                where = data['symbol']['location']
                try:
                    preview = await asyncio.to_thread(self.provider.preview, SymbolLocation(**where))
                except (OSError, ValueError, UnicodeError, SyntaxError):
                    data['warnings'] = [*data['warnings'], 'Source preview unavailable; refresh after editing']
            if generation != self._generation:
                return
            self.data = data
            self.query_one('#trace-breadcrumb', Static).update(
                ' → '.join([item[0] for item in self.history[-4:]] + [target]))
            detail = self.query_one(RichLog)
            detail.clear()
            detail.write(Text(format_trace(data, outgoing=mode == 'outgoing', to_entry=mode == 'entries')))
            if preview:
                detail.write(Text('\nSource preview', style='bold'))
                for number, line in preview:
                    detail.write(Text(f'{number:>5} │ {line}'))

            def add(symbol, note=''):
                if options.option_count >= 200:
                    return
                where = symbol['location']
                destination = f"{where['path']}:{where['line']}"
                self._options.append((destination, 'incoming'))
                options.add_option(Option(Text(f"{symbol['qualified_name']}  {destination} {note}"),
                                          id=str(len(self._options)-1)))

            if len(data['candidates']) > 200:
                detail.write(Text('[Candidate list limited to 200; refine the query]'))
            for symbol in data['candidates'][:200]:
                add(symbol, '[choose symbol]')
            if mode == 'entries':
                seen = set()
                for path in data['paths']:
                    for symbol in path['nodes']:
                        if symbol['id'] not in seen and len(self._options) < 200:
                            add(symbol)
                            seen.add(symbol['id'])
            else:
                for relation in data['outgoing' if mode == 'outgoing' else 'incoming'][:200]:
                    symbol = relation['callee'] if mode == 'outgoing' else relation['caller']
                    if symbol:
                        add(symbol, f"[{relation['resolution']}]")
                    elif relation['candidates']:
                        for symbol in relation['candidates'][:20]:
                            add(symbol, '[ambiguous candidate]')
                    else:
                        if options.option_count < 200:
                            options.add_option(Option(Text(f"{relation['expression']} [unresolved]"), disabled=True))
            if options.option_count == 200:
                detail.write(Text('[Navigation list limited to 200; refine the query]'))
            if options.option_count:
                options.highlighted = 0
        except Exception as exc:
            self.query_one('#trace-status', Static).update(f'Trace query unavailable: {type(exc).__name__}')

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if event.option.id is not None:
            target, mode = self._options[int(event.option.id)]
            self.navigate(target, mode)
        event.stop()

    def action_back(self):
        if self.history:
            self.target, self.mode = self.history.pop()
            self.show_target()
        else:
            self.dismiss()

    def action_incoming(self):
        self.mode = 'incoming'
        self.show_target()

    def action_outgoing(self):
        self.mode = 'outgoing'
        self.show_target()

    def action_entries(self):
        self.mode = 'entries'
        self.show_target()

    def action_search(self):
        self.query_one(Input).focus()

    def on_unmount(self):
        self._generation += 1
