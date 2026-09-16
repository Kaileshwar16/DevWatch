"""Conservative lexical/import resolution over parsed data, without type inference."""
from __future__ import annotations

from devdash.trace.models import CallRelation, TraceIndex
from devdash.trace.python import Binding, ParsedFile


class Resolver:
    def __init__(self, files: list[ParsedFile]):
        self.scopes = {key: scope for file in files for key, scope in file.scopes.items()}
        self.files = {key: file for file in files for key in file.scopes}
        self.modules: dict[str, list[str]] = {}
        self._resolved: dict[tuple[str, tuple[str, ...]], set[Binding]] = {}
        for file in files:
            module_scope = next(iter(file.scopes))
            for name in file.modules:
                self.modules.setdefault(name, []).append(module_scope)

    def lexical(self, scope_id: str, name: str) -> tuple[str, list[Binding]]:
        original = scope_id
        while scope_id:
            scope = self.scopes[scope_id]
            # Class namespaces are not lexical closures for methods/nested methods.
            if scope_id == original or scope.symbol.kind != 'class':
                if name in scope.bindings:
                    return scope_id, scope.bindings[name]
                if '*' in scope.bindings:
                    return scope_id, [Binding('unknown')]
            scope_id = scope.parent
        return original, [Binding('unknown')]

    def qualified(self, name: str, seen: frozenset) -> set[Binding]:
        if len(seen) >= 32 or ('qualified', name) in seen:
            return {Binding('unknown')}
        seen = seen | {('qualified', name)}
        if name in self.modules:
            return {Binding('module', name)}
        parts = name.split('.')
        for length in range(len(parts) - 1, 0, -1):
            module = '.'.join(parts[:length])
            if module in self.modules:
                result = set()
                for scope_id in self.modules[module]:
                    bindings = self.scopes[scope_id].bindings.get(parts[length], [Binding('unknown')])
                    for binding in bindings:
                        for value in self.expand(binding, scope_id, seen):
                            result.update(self.attributes(value, tuple(parts[length + 1:]), seen))
                return result
        return {Binding('unknown')}

    def expand(self, binding: Binding, scope_id: str, seen: frozenset) -> set[Binding]:
        if binding.kind != 'import':
            return {binding}
        if len(seen) >= 32 or (scope_id, binding.target) in seen:
            return {Binding('unknown')}
        seen = seen | {(scope_id, binding.target)}
        module, name = binding.target.split(':', 1)
        level = len(module) - len(module.lstrip('.'))
        file = self.files[scope_id]
        if not level:
            return self.qualified('.'.join(filter(None, (module, name))), seen)
        result = set()
        for current in file.modules:
            package = current.split('.') if file.path.endswith('/__init__.py') else current.split('.')[:-1]
            if len(package) < level:
                result.add(Binding('unknown'))
                continue
            prefix = package[:len(package) - level + 1]
            target = '.'.join([*prefix, *filter(None, (module.lstrip('.'), name))])
            result.update(self.qualified(target, seen))
        return result or {Binding('unknown')}

    def attributes(self, binding: Binding, parts: tuple[str, ...], seen: frozenset) -> set[Binding]:
        if not parts:
            return {binding}
        if binding.kind == 'module':
            return self.qualified('.'.join((binding.target, *parts)), seen)
        if binding.kind in ('symbol', 'receiver'):
            scope = self.scopes[binding.target]
            if scope.symbol.kind == 'class':
                values = set()
                for member in scope.bindings.get(parts[0], [Binding('unknown')]):
                    for value in self.expand(member, binding.target, seen):
                        values.update(self.attributes(value, parts[1:], seen))
                return values
        return {Binding('unknown')}

    def resolve(self, owner: str, parts: tuple[str, ...]) -> set[Binding]:
        key = (owner, parts)
        if key not in self._resolved:
            self._resolved[key] = self._resolve(owner, parts)
        return self._resolved[key]

    def _resolve(self, owner: str, parts: tuple[str, ...]) -> set[Binding]:
        if not parts:
            return {Binding('unknown')}
        scope_id = owner
        while scope_id:
            scope = self.scopes[scope_id]
            if any(parts[:len(rebound)] == rebound for rebound in scope.rebound_attributes):
                return {Binding('unknown')}
            scope_id = scope.parent
        scope, bindings = self.lexical(owner, parts[0])
        result = set()
        for binding in bindings:
            for value in self.expand(binding, scope, frozenset()):
                result.update(self.attributes(value, parts[1:], frozenset()))
        return result

    def populate(self, index: TraceIndex, files: list[ParsedFile]):
        candidate_count = 0
        for file in files:
            for call in file.calls:
                values = self.resolve(call.owner, call.parts)
                targets = sorted({self.scopes[value.target].symbol for value in values if value.kind == 'symbol'},
                                 key=lambda symbol: symbol.id)
                unknown = any(value.kind != 'symbol' for value in values)
                if len(targets) == 1 and not unknown:
                    resolution, callee, candidates = 'resolved', targets[0], ()
                    reason = 'Lexical/import binding; possible static relationship'
                elif targets:
                    resolution, callee, candidates = 'ambiguous', None, tuple(targets[:100])
                    reason = 'Multiple possible bindings or a binding also reassigned dynamically'
                    candidate_count += len(candidates)
                    if len(targets) > 100 or candidate_count > 100000:
                        index.truncated = True
                        if not any('Ambiguous target' in warning for warning in index.warnings):
                            index.warnings.append('Ambiguous target limit reached; some candidate relationships omitted')
                        if candidate_count > 100000:
                            candidates = ()
                else:
                    resolution, callee, candidates = 'unresolved', None, ()
                    reason = 'External, builtin, dynamic, or unknown binding; no project target established'
                index.relations.append(CallRelation(index.symbols[call.owner], call.expression,
                                                    call.location, resolution, callee, candidates, reason))
