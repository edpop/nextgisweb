# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from collections import namedtuple

from bunch import Bunch

from .. import db
from ..models import declarative_base
from ..registry import registry_maker
from ..auth import Principal, User, Group

from .interface import providedBy
from .serialize import (
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR,
    SerializedResourceRelationship as SRR)
from .scope import ResourceScope, MetadataScope
from .exception import ResourceError, Forbidden

__all__ = ['Resource', ]

Base = declarative_base()

resource_registry = registry_maker()

PermissionSets = namedtuple('PermissionSets', ('allow', 'deny', 'mask'))


class ResourceMeta(db.DeclarativeMeta):

    def __init__(cls, classname, bases, nmspc):

        # По-умолчанию имя таблицы совпадает с идентификатором ресурса.
        # Вряд ли когда-то потребуется по-другому, но на всяких случай
        # оставим такую возможность.

        if '__tablename__' not in cls.__dict__:
            setattr(cls, '__tablename__', cls.identity)

        # Дочерний класс может указать какие-то свои аргументы, оставим
        # ему такую возможность. Если не указано, указываем свои.

        if '__mapper_args__' not in cls.__dict__:
            mapper_args = dict()
            setattr(cls, '__mapper_args__', mapper_args)
        else:
            mapper_args = getattr(cls, '__mapper_args__')

        if 'polymorphic_identity' not in mapper_args:
            mapper_args['polymorphic_identity'] = cls.identity

        # Для класса Resource эта переменная еще не определена.
        Resource = globals().get('Resource', None)

        if Resource and cls != Resource:

            # Для дочерних классов нужна колонка с внешним ключем, указывающим
            # на базовый класс ресурса. Возможно потребуется создать вручную,
            # но проще для всех ее создать разом.

            if 'id' not in cls.__dict__:
                idcol = db.Column('id', db.ForeignKey(Resource.id),
                                  primary_key=True)
                idcol._creation_order = Resource.id._creation_order
                setattr(cls, 'id', idcol)

            # Автоматическое определение поля по которому происходит связь
            # с родителем не работает в случае, если есть два поля с внешним
            # ключем на resource.id.

            if 'inherit_condition' not in mapper_args:
                mapper_args['inherit_condition'] = (
                    cls.id == Resource.id)

        scope = Bunch()

        for base in cls.__mro__:
            bscope = base.__dict__.get('__scope__', None)

            if bscope is None:
                continue

            if bscope and not hasattr(bscope, '__iter__'):
                bscope = tuple((bscope, ))

            for s in bscope:
                scope[s.identity] = s

        setattr(cls, 'scope', scope)

        super(ResourceMeta, cls).__init__(classname, bases, nmspc)

        resource_registry.register(cls)


class Resource(Base):
    __metaclass__ = ResourceMeta
    registry = resource_registry

    identity = 'resource'
    cls_display_name = "Ресурс"

    __scope__ = (ResourceScope, MetadataScope)

    id = db.Column(db.Integer, primary_key=True)
    cls = db.Column(db.Unicode, nullable=False)

    parent_id = db.Column(db.ForeignKey(id))

    keyname = db.Column(db.Unicode, unique=True)
    display_name = db.Column(db.Unicode, nullable=False)

    owner_user_id = db.Column(db.ForeignKey(User.id), nullable=False)

    description = db.Column(db.Unicode)

    __mapper_args__ = dict(polymorphic_on=cls)

    parent = db.relationship(
        'Resource', remote_side=[id],
        backref=db.backref(
            'children',
            order_by=display_name,
            cascade="delete"))

    owner_user = db.relationship(User)

    def __unicode__(self):
        return self.display_name

    def check_child(self, child):
        """ Может ли этот ресурс принять child в качестве дочернего """
        return False

    @classmethod
    def check_parent(self, parent):
        """ Может ли этот ресурс быть дочерним для parent """
        return False

    @property
    def parents(self):
        """ Список всех родителей от корня до непосредственного родителя """
        result = []
        current = self
        while current.parent:
            current = current.parent
            result.append(current)

        return reversed(result)

    # Права доступа

    @classmethod
    def class_permissions(cls):
        """ Права применимые к этому классу ресурсов """

        result = set()
        for scope in cls.scope.itervalues():
            result.update(scope.itervalues())

        return frozenset(result)

    def permission_sets(self, user):
        class_permissions = self.class_permissions()

        allow = set()
        deny = set()
        mask = set()

        for res in tuple(self.parents) + (self, ):
            rules = filter(lambda (rule): (
                (rule.propagate or res == self)
                and rule.cmp_identity(self.identity)
                and rule.cmp_user(user)),
                res.acl)

            for rule in rules:
                for perm in class_permissions:
                    if rule.cmp_permission(perm):
                        if rule.action == 'allow':
                            allow.add(perm)
                        elif rule.action == 'deny':
                            deny.add(perm)

        for a in class_permissions:
            passed = True
            for scp in self.scope.itervalues():
                if not passed:
                    continue

                for req in scp.requirements:
                    if not passed:
                        continue

                    if req.dst == a and (
                        req.cls is None
                        or isinstance(self, req.cls)
                    ):
                        if req.attr is None:
                            p = req.src in allow and req.src not in deny
                        else:
                            attrval = getattr(self, req.attr)
                            p = attrval is not None \
                                and attrval.has_permission(req.src, user)

                        passed = passed and p

            if not passed:
                mask.add(a)

        return PermissionSets(allow=allow, deny=deny, mask=mask)

    def permissions(self, user):
        sets = self.permission_sets(user)
        return sets.allow - sets.mask - sets.deny

    def has_permission(self, permission, user):
        return permission in self.permissions(user)


class _parent_attr(SRR):

    def writeperm(self, srlzr):
        return True

    def setter(self, srlzr, value):
        super(_parent_attr, self).setter(srlzr, value)
        ref = srlzr.obj.parent

        if not ref.has_permission(ResourceScope.manage_children, srlzr.user):
            raise Forbidden()

        if not srlzr.obj.check_parent(ref):
            raise ResourceError("Parentship error")

        # TODO: check_child


class _children_attr(SP):
    def getter(self, srlzr):
        return len(srlzr.obj.children) > 0


class _interfaces_attr(SP):
    def getter(self, srlzr):
        return map(lambda i: i.getName(), providedBy(srlzr.obj))


class _scopes_attr(SP):
    def getter(self, srlzr):
        return srlzr.obj.scope.keys()


def _ro(c):
    _scp = Resource.scope.resource
    return c(read=_scp.read, write=None, depth=2)


def _rw(c):
    _scp = Resource.scope.resource
    return c(read=_scp.read, write=_scp.update, depth=2)


class ResourceSerializer(Serializer):
    identity = Resource.identity
    resclass = Resource

    id = _ro(SP)
    cls = _ro(SP)

    parent = _rw(_parent_attr)
    owner_user = _ro(SR)

    keyname = _rw(SP)
    display_name = _rw(SP)

    description = SP(read=MetadataScope.read, write=MetadataScope.write)

    children = _ro(_children_attr)
    interfaces = _ro(_interfaces_attr)
    scopes = _ro(_scopes_attr)


class ResourceACLRule(Base):
    __tablename__ = "resource_acl_rule"

    resource_id = db.Column(db.ForeignKey(Resource.id), primary_key=True)
    principal_id = db.Column(db.ForeignKey(Principal.id), primary_key=True)

    identity = db.Column(db.Unicode, primary_key=True, default='')
    identity.__doc__ = """
        Тип ресурса для которого действует это правило. Пустая строка
        означает, что оно действует для всех типов ресурсов."""

    # Право для которого действует это правило. Пустая строка означает
    # полный набор прав для всех типов ресурсов.
    scope = db.Column(db.Unicode, primary_key=True, default='')
    permission = db.Column(db.Unicode, primary_key=True, default='')

    propagate = db.Column(db.Boolean, primary_key=True, default=True)
    propagate.__doc__ = """
        Следует ли распространять действие этого правила на дочерние ресурсы
        или оно действует только на ресурс в котором указано."""

    action = db.Column(db.Unicode, nullable=False, default=True)
    action.__doc__ = """
        Действие над правом: allow (разрешение) или deny (запрет). При этом
        правила запрета имеют приоритет над разрешениями."""

    resource = db.relationship(
        Resource, backref=db.backref(
            'acl', cascade='all, delete-orphan'))

    principal = db.relationship(Principal)

    def cmp_user(self, user):
        principal = self.principal
        return (isinstance(principal, User) and principal.compare(user)) \
            or (isinstance(principal, Group) and principal.is_member(user))

    def cmp_identity(self, identity):
        return (self.identity == '') or (self.identity == identity)

    def cmp_permission(self, permission):
        pname = permission.name
        pscope = permission.scope.identity

        return ((self.scope == '' and self.permission == '')
                or (self.scope == pscope and self.permission == '')
                or (self.scope == pscope and self.permission == pname))


class ResourceGroup(Resource):
    identity = 'resource_group'
    cls_display_name = "Группа ресурсов"

    def check_child(self, child):
        # Принимаем любые дочерние ресурсы
        return True

    @classmethod
    def check_parent(self, parent):
        # Группа может быть либо корнем, либо подгруппой в другой группе
        return (parent is None) or isinstance(parent, ResourceGroup)