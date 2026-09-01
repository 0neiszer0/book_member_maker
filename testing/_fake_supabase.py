from copy import deepcopy
from types import SimpleNamespace


class FakeQuery:
    """Small PostgREST query double used by route and render tests."""

    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.filters = []
        self.orders = []
        self.limit_value = None
        self.range_value = None
        self.single_value = False
        self.count_mode = None
        self.operation = "select"
        self.payload = None

    def _record(self, method, *args, **kwargs):
        self.client.calls.append((method, self.table_name, args, kwargs))
        return self

    def select(self, *columns, **kwargs):
        self.operation = "select"
        self.count_mode = kwargs.get("count")
        return self._record("select", *columns, **kwargs)

    def insert(self, payload):
        self.operation = "insert"
        self.payload = deepcopy(payload)
        return self._record("insert", payload)

    def update(self, payload):
        self.operation = "update"
        self.payload = deepcopy(payload)
        return self._record("update", payload)

    def delete(self):
        self.operation = "delete"
        return self._record("delete")

    def eq(self, column, value):
        self.filters.append(lambda row: row.get(column) == value)
        return self._record("eq", column, value)

    def neq(self, column, value):
        self.filters.append(lambda row: row.get(column) != value)
        return self._record("neq", column, value)

    def in_(self, column, values):
        accepted = set(values)
        self.filters.append(lambda row: row.get(column) in accepted)
        return self._record("in_", column, tuple(values))

    def gte(self, column, value):
        self.filters.append(
            lambda row: row.get(column) is not None and row.get(column) >= value
        )
        return self._record("gte", column, value)

    def lte(self, column, value):
        self.filters.append(
            lambda row: row.get(column) is not None and row.get(column) <= value
        )
        return self._record("lte", column, value)

    def is_(self, column, value):
        expected = None if value == "null" else value
        self.filters.append(lambda row: row.get(column) is expected)
        return self._record("is_", column, value)

    def order(self, column, desc=False, **kwargs):
        self.orders.append((column, desc))
        return self._record("order", column, desc=desc, **kwargs)

    def limit(self, value):
        self.limit_value = value
        return self._record("limit", value)

    def range(self, start, end):
        self.range_value = (start, end)
        return self._record("range", start, end)

    def single(self):
        self.single_value = True
        return self._record("single")

    def execute(self):
        self._record("execute")
        source_rows = self.client.rows.setdefault(self.table_name, [])
        matching_indexes = [
            index
            for index, row in enumerate(source_rows)
            if all(predicate(row) for predicate in self.filters)
        ]

        if self.operation == "insert":
            inserted = deepcopy(self.payload)
            source_rows.append(inserted)
            return SimpleNamespace(data=[deepcopy(inserted)], count=None)
        if self.operation == "update":
            updated = []
            for index in matching_indexes:
                source_rows[index].update(deepcopy(self.payload))
                updated.append(deepcopy(source_rows[index]))
            return SimpleNamespace(data=updated, count=None)
        if self.operation == "delete":
            deleted = [deepcopy(source_rows[index]) for index in matching_indexes]
            self.client.rows[self.table_name] = [
                row for index, row in enumerate(source_rows) if index not in matching_indexes
            ]
            return SimpleNamespace(data=deleted, count=None)

        rows = [deepcopy(source_rows[index]) for index in matching_indexes]
        for column, desc in reversed(self.orders):
            rows.sort(
                key=lambda row: (row.get(column) is None, row.get(column)),
                reverse=desc,
            )
        count = len(rows) if self.count_mode == "exact" else None
        if self.range_value is not None:
            start, end = self.range_value
            rows = rows[start:end + 1]
        if self.limit_value is not None:
            rows = rows[:self.limit_value]
        data = (rows[0] if rows else None) if self.single_value else rows
        return SimpleNamespace(data=data, count=count)


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = deepcopy(rows or {})
        self.calls = []

    def table(self, table_name):
        self.calls.append(("table", table_name, (), {}))
        return FakeQuery(self, table_name)
