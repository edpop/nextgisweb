# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from collections import namedtuple

import sqlalchemy as sa
import sqlalchemy.orm as orm

from ..models import declarative_base
from ..registry import registry_maker
from ..auth import Principal, User, Group

from .scope import clscopes, scopeid
from .interface import providedBy
from .serialize import (
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR,
    SerializedResourceRelationship as SRR)
from .permission import register_permission, scope_permissions
from .exception import ResourceError, Forbidden

Base = declarative_base()

resource_registry = registry_maker()

PermissionSets = namedtuple('PermissionSets', ('allow', 'deny'))


@resource_registry.register
class Resource(Base):
    identity = 'resource'
    cls_display_name = "Ресурс"

    registry = resource_registry

    __tablename__ = 'resource'

    id = sa.Column(sa.Integer, primary_key=True)
    parent_id = sa.Column(sa.ForeignKey(id))

    cls = sa.Column(sa.Unicode, nullable=False)

    keyname = sa.Column(sa.Unicode, unique=True)
    display_name = sa.Column(sa.Unicode, nullable=False)

    owner_user_id = sa.Column(sa.ForeignKey(User.id), nullable=False)

    description = sa.Column(sa.Unicode)

    __mapper_args__ = {
        'polymorphic_identity': __tablename__,
        'polymorphic_on': cls
    }

    parent = orm.relationship(
        'Resource', remote_side=[id],
        backref=orm.backref('children',
                            order_by=display_name,
                            cascade="delete")
    )

    owner_user = orm.relationship(User)

    def __init__(self, **kwargs):
        super(Base, self).__init__(**kwargs)

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
        for scope in clscopes(cls):
            result.update(scope_permissions(scope).itervalues())

        return frozenset(result)

    def permission_sets(self, user):
        class_permissions = self.class_permissions()

        allow = set()
        deny = set()

        for res in tuple(self.parents) + (self, ):
            rules = filter(lambda (rule): (
                (rule.propagate or res == self)
                and rule.cmp_identity(self.identity)
                and rule.cmp_user(user)),
                res.acl)

            for rule in rules:
                for perm in class_permissions:
                    if rule.cmp_permission(perm.scope, perm.permission):
                        if rule.action == 'allow':
                            allow.add(perm)
                        elif rule.action == 'deny':
                            deny.add(perm)

        return PermissionSets(allow=allow, deny=deny)

    def permissions(self, user):
        sets = self.permission_sets(user)
        return sets.allow - sets.deny

    def has_permission(self, cls, permission, user):
        return (
            scope_permissions(cls)[permission]
            in self.permissions(user)
        )


register_permission(
    Resource, 'identify',
    "Идентификация ресурса")

register_permission(
    Resource, 'create',
    "Создание ресурса")

register_permission(
    Resource, 'edit',
    "Изменение ресурса")

register_permission(
    Resource, 'delete',
    "Удаление ресурса")

register_permission(
    Resource, 'permissions',
    "Управление правами доступа")

register_permission(
    Resource, 'children',
    "Управление дочерними ресурсами")


class _parent_attr(SRR):

    def writeperm(self, srlzr):
        return True

    def setter(self, srlzr, value):
        super(_parent_attr, self).setter(srlzr, value)
        ref = srlzr.obj.parent

        if not ref.has_permission(Resource, 'children', srlzr.user):
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
        return map(scopeid, clscopes(srlzr.obj.__class__))


class ResourceSerializer(Serializer):
    identity = Resource.identity
    resclass = Resource

    id = SP(read='identify')
    cls = SP(read='identify')

    parent = _parent_attr(read='identify', write='identify')
    owner_user = SR(read='identify')

    keyname = SP(read='identify', write='edit')
    display_name = SP(read='identify', write='edit')

    children = _children_attr(read='identify')
    interfaces = _interfaces_attr(read='identify')
    scopes = _scopes_attr(read='identify')


class ResourceACLRule(Base):
    __tablename__ = "resource_acl_rule"

    resource_id = sa.Column(sa.ForeignKey(Resource.id), primary_key=True)
    principal_id = sa.Column(sa.ForeignKey(Principal.id), primary_key=True)

    # Тип ресурса для которого действует это правило. Пустая строка
    # означает, что оно действует для всех типов ресурсов.
    identity = sa.Column(sa.Unicode, primary_key=True, default='')

    # Право для которого действует это правило. Пустая строка означает
    # полный набор прав для всех типов ресурсов.
    scope = sa.Column(sa.Unicode, primary_key=True, default='')
    permission = sa.Column(sa.Unicode, primary_key=True, default='')

    # Распространять правило на дочерние ресурсы или нет
    propagate = sa.Column(sa.Boolean, primary_key=True, default=True)

    # Действие над правом: allow (разрешение) или deny (запрет).
    # При этом правила запрета имеют приоритет над разрешениями.
    action = sa.Column(sa.Unicode, nullable=False, default=True)

    resource = orm.relationship(
        Resource, backref=orm.backref(
            'acl', cascade='all, delete-orphan'))

    principal = orm.relationship(Principal)

    def cmp_user(self, user):
        principal = self.principal
        return (isinstance(principal, User) and principal.compare(user)) \
            or (isinstance(principal, Group) and principal.is_member(user))

    def cmp_identity(self, identity):
        return (self.identity == '') or (self.identity == identity)

    def cmp_permission(self, scope, permission):
        return ((self.scope == '') and (self.permission == '')) \
            or ((self.scope == scope) and (self.permission == '')) \
            or ((self.scope == scope) and (self.permission == permission))


class MetaDataScope(object):
    identity = 'metadata'
    cls_display_name = "Метаданные"


register_permission(
    MetaDataScope, 'view',
    "Просмотр метаданных")

register_permission(
    MetaDataScope, 'edit',
    "Изменение метаданных")


class DataScope(MetaDataScope):
    identity = 'data'
    cls_display_name = "Данные"


register_permission(
    DataScope, 'view',
    "Просмотр данных")

register_permission(
    DataScope, 'edit',
    "Изменение данных")


@Resource.registry.register
class ResourceGroup(MetaDataScope, Resource):

    identity = 'resource_group'
    cls_display_name = "Группа ресурсов"

    __tablename__ = identity
    __mapper_args__ = dict(polymorphic_identity=identity)

    resource_id = sa.Column(sa.ForeignKey(Resource.id), primary_key=True)

    def check_child(self, child):
        # Принимаем любые дочерние ресурсы
        return True

    @classmethod
    def check_parent(self, parent):
        # Группа может быть либо корнем, либо подгруппой в другой группе
        return (parent is None) or isinstance(parent, ResourceGroup)
