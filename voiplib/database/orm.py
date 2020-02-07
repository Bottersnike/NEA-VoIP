import threading
import sqlite3


ALLOWED_TYPES = {
    int: 'INTEGER',
    str: 'TEXT',
    float: 'FLOAT',
    bool: 'BOOLEAN',
}


class Wrapper:
    def __init__(self, wraps):
        self.wraps = wraps

    @classmethod
    def __class_getitem__(cls, item):
        return cls(item)
    
    def unwrap(self):
        w = self.wraps
        while isinstance(w, Wrapper):
            w = w.wraps
        return w


class NotNull(Wrapper):
    pass


class Primary(Wrapper):
    pass


class List(Wrapper):
    pass


class Auto(Wrapper):
    pass


class List_:
    def __init__(self, tab, record, of, items):
        self._tab = tab
        self._record = record
        self._of = of
        for i in items:
            self.append(i)
    
    def append(self, i):
        if i._id is None:
            i._table.insert(i)
        
        class Doc:
            pass
        d = Doc()
        d.cols = {
            self._tab.magic[0]: getattr(self._record, self._record._table.primary._field),
            self._tab.magic[1]: getattr(i, i._table.primary._field)
        }
        self._tab.magic[2].insert(d)
    
    def all_items(self):
        query = f'''SELECT * FROM {self._tab.magic[2]};'''
        return_value = []
        ready = threading.Event()

        def f():
            cur = self._tab._db.connection.cursor()
            cur.execute(query)
            dat = cur.fetchall()
            cur.close()
            return_value.append(dat)
            ready.set()
        
        self._tab._db.enqueue(f)
        ready.wait()
        dat = return_value.pop()

        return [self._record._table(*i) for i in dat]

    def __str__(self):
        return '[' + ', '.join(map(lambda x: f'<{x}>', self.all_items())) + ']'


class Reference:
    def __init__(self, db, table, field, type_, original=None):
        self._db = db
        self._table = table
        self._field = field
        self._type = type_
        self._original = original

    def get_table(self):
        return self._table

    def prepare(self, simple=False):
        stmt = defer = ''

        if self._type in ALLOWED_TYPES:
            stmt = f'{self._field} {ALLOWED_TYPES[self._type]}'
        elif isinstance(self._type, self.__class__):
            defer = f'FOREIGN KEY ({self._field}) REFERENCES {self._type._table}({self._type._field})'
            ext, d = self._type.prepare()
            if d:
                defer += ',' + d
            ext = ext.split(' ', 1)[-1]
            stmt = str(self._field) + ' ' + ext

            if simple:
                return str(self._field) + ' ' + ext

        elif isinstance(self._type, Table):
            defer = f'FOREIGN KEY ({self._field}) REFERENCES {self._type.primary}'
            ext, d = self._type.primary.prepare(True)
            if d:
                defer += ',' + d
            ext = ext.split(' ', 1)[-1]
            stmt = str(self._field) + ' ' + ext

            if simple:
                return str(self._field) + ' ' + ext

        if self._original and not simple:
            for i in self._original[::-1]:
                if isinstance(i, NotNull):
                    stmt += ' NOT NULL'
                elif isinstance(i, Primary):
                    stmt += ' PRIMARY KEY'
                elif isinstance(i, Auto):
                    stmt += ' AUTOINCREMENT'

        return (stmt, defer)

    def __str__(self):
        if self._field:
            return f'{self._table}({self._field})'
        return self._table


class Record:
    def __init__(self, cols, table):
        self.__dict__['cols'] = cols
        self.__dict__['_table'] = table

    def get_table(self):
        return self.__dict__['_table']

    def __getattr__(self, attr):
        return self.__dict__['cols'][attr]
    
    def __setattr__(self, attr, value):
        self.__dict__['cols'][attr] = value
    
    def __str__(self):
        return ', '.join(f'{i}: {repr(self.__dict__["cols"][i])}' for i in self.__dict__['cols'])
    
    def __repr__(self):
        return f'<{self}>'


class Table:
    class NoneValue:
        pass

    NoneValue = NoneValue()

    def __init__(self, db, name):
        self._db = db
        self._name = name

        self.primary = None
        self.fields = []

    def prepare(self, exist_ok=False):
        stmt = f'CREATE TABLE {"IF NOT EXISTS " if exist_ok else ""}' + self._name + '(\n'

        deferred = []
        for i in self.fields:
            if i._original and list in i._original:
                continue
            s, d = i.prepare()
            if d:
                deferred.append(d)
            stmt += '  ' + s + ',\n'
        for i in deferred:
            stmt += '  ' + i + ',\n'

        stmt = stmt.strip(',\n') + '\n'
        stmt += ');'
        return stmt

    def __call__(self, *args, **kwargs):
        fields = {}
        args = list(args)

        if self.fields[0] == self.primary and self.primary._field == '_id':
            if len(args) < len(self.fields):
                args.insert(0, None)
     
        for i in self.fields:
            if i._original:
                for j in i._original:
                    pass

                    #if isinstance(j, Auto):
                    #    fields[j.unwrap()._field] = self.NoneValue

        for n, i in enumerate(args):
            if len(fields) == len(self.fields):
                raise AttributeError('Passed arguments fail to match table structure')
            fields[self.fields[n]] = i
        for i in kwargs:
            if i not in self.fields or i in fields:
                raise AttributeError('Passed arguments fail to match table structure')
            fields[i] = kwargs[i]
        
        lists = [i for i in fields if isinstance(fields[i], list)]

        _fields = {}
        for i in fields:
            _fields[i._field] = None if i in lists else fields[i]

        record = Record(_fields, self)

        for i in lists:
            record.__dict__['cols'][i._field] = List_(self, record, i, fields[i])
        return record

    def __str__(self):
        return self._name
    
    def select(self, **kwargs):
        if '___database_thread' in kwargs:
            ___database_thread = True
            kwargs.pop('___database_thread')
        else:
            ___database_thread = False
        
        selector, args = [], []
        fields = [i._field for i in self.fields]
        for i in kwargs:
            if i not in fields:
                raise AttributeError('No column \'' + i + '\'')
            selector.append(f'{i}=?')
            args.append(kwargs[i])

        query = f'SELECT * FROM {self._name}'
        if selector:
            query += f' WHERE ' + ' AND '.join(selector)

        return_value = []
        ready = threading.Event()

        def f():
            cur = self._db.connection.cursor()
            cur.execute(query, args)
            res = cur.fetchall()

            ret = []
            for i in res:
                row = []
                for j, r in zip(i, self.fields):
                    if isinstance(r._type, Table):
                        j = r._type.select(**{r._type.primary._field: j}, ___database_thread=True)[0]
                    row.append(j)
                ret.append(self(*row))

            return_value.append(ret)
            ready.set()
        
        if ___database_thread:
            f()
        else:
            self._db._enqueue(f)
            ready.wait()
        return return_value[0]
    
    def insert(self, document):
        args = []
        fields = [i._field for i in self.fields]
        
        for i in document.cols:
            if i not in fields:
                raise AttributeError('No column \'' + i + '\'')
        for i in fields:
            if i in document.cols:
                if isinstance(document.cols[i], Record):
                    pk = document.cols[i].get_table()
                    pk = getattr(document.cols[i], pk.primary._field)
                    args.append(pk)
                elif isinstance(document.cols[i], List_):
                    pass
                else:
                    args.append(document.cols[i])
            else:
                args.append(None)

        selector = ', '.join(['?'] * len(args))
        query = f'INSERT INTO {self._name} VALUES ({selector})'

        ready = threading.Event()
        def f():
            cur = self._db.connection.cursor()
            cur.execute(query, args)
            self._db.connection.commit()

            if self.primary:
                if self.primary._field == '_id':
                    id_ = cur.lastrowid
                    document._id = id_

            cur.close()
            ready.set()

        self._db._enqueue(f)
        ready.wait()


class DB:
    def __init__(self, path):
        self.tables = []

        self.connection = None
        threading.Thread(target=self._monitor, args=(path, ), daemon=True).start()

        self._queue = []
        self._queue_ready = threading.Event()
        self._queue_lock = threading.Lock()
    
    def _enqueue(self, f):
        with self._queue_lock:
            self._queue.append(f)
            self._queue_ready.set()

    def _monitor(self, path):
        self.connection = sqlite3.connect(path)

        while True:
            self._queue_ready.wait()
            with self._queue_lock:
                item = self._queue.pop(0)
                if not self._queue:
                    self._queue_ready.clear()

            item()

    def object(self, obj_class):
        attributes = obj_class.__annotations__
        obj_class._fields = []
        table = Table(self, obj_class.__name__)

        for i in attributes:
            if attributes[i] not in ALLOWED_TYPES and not isinstance(attributes[i], (Table, Reference, Wrapper)):
                raise ValueError('Unsupported type:', attributes[i])

            original = [attributes[i]]
            while isinstance(attributes[i], Wrapper):
                if attributes[i].wraps not in ALLOWED_TYPES and not isinstance(attributes[i].wraps, (Table, Reference)):
                    raise ValueError('Unsupported type:', attributes[i].wraps)
                attributes[i] = attributes[i].wraps
                original.append(attributes[i])

            if isinstance(original[0], List):
                if isinstance(attributes[i], Table):
                    r_table = attributes[i]
                else:
                    r_table = attributes[i].get_table()

                new_t = Table(self, f'___{table}__{r_table}')
                new_t.fields.append(
                    Reference(self, new_t, str(table), int)
                )
                new_t.fields.append(
                    Reference(self, new_t, str(r_table), r_table.primary)
                )
                self.tables.append(new_t)
                new_t.magic = [str(table), str(r_table), new_t]
                table.magic = [str(table), str(r_table), new_t]

                ref = Reference(self, table, i, Reference(self, new_t, str(table), int), [list])
            else:
                ref = Reference(self, table, i, attributes[i], original)

            table.fields.append(ref)
            setattr(table, i, ref)

            if isinstance(original[0], Primary):
                if table.primary is not None:
                    raise ValueError('Table cannot have multiple primary keys!')
                table.primary = ref

        if table.primary is None:
            ref = Reference(self, table, '_id', int, [Auto[Primary[int]], Primary[int], int])
            table.fields.insert(0, ref)
            table._id = ref
            table.primary = ref

        self.tables.append(table)

        return table

    def prepare(self, exist_ok=False):
        ready = threading.Event()
        def f():
            cur = self.connection.cursor()
            for i in self.tables:
                print(i.prepare(exist_ok))
                #cur.execute(i.prepare(exist_ok))
            cur.close()

            ready.set()
        self._enqueue(f)
        ready.wait()

