from orm import DB, Primary, NotNull, List

db = DB(':memory:')


@db.object
class TestObject1:
    name: Primary[str]
    age: NotNull[int]


@db.object
class TestObject2:
    help_me: float
    to1: TestObject1


@db.object
class TestObject3:
    to2: TestObject2.to1


@db.object
class TestObject4:
    objects: List[TestObject3]


db.prepare()

obj = TestObject1('name', 5)

print(TestObject1.select(name='name'))
TestObject1.insert(obj)
obj.name = 'test'
TestObject1.insert(obj)
print(TestObject1.select())
print(TestObject1.select(name='name'))

ob2 = TestObject2(0.5, obj)
ob3 = TestObject3(ob2)

ob4 = TestObject4([])
TestObject2.insert(ob2)
TestObject4.insert(ob4)
ob4.objects.append(ob3)

print(TestObject2.select())

print(ob4)

print(ob4.objects)
