# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import sys
from collections import OrderedDict

from zope import interface

from ..registry import registry_maker
from ..models import BaseClass

from .permission import permission
from .exception import Forbidden

_registry = registry_maker()


class SerializerBase(object):

    def __init__(self, obj, user, data=None):
        self.obj = obj
        self.user = user

        if data is None:
            self.data = OrderedDict()
            self.keys = None
        else:
            self.data = data
            self.keys = set()

    def is_applicable(self):
        pass

    def serialize(self):
        pass

    def deserialize(self):
        pass

    def mark(self, *keys):
        self.keys.update(keys)

    def has_permission(self, cls, permission):
        return self.obj.has_permission(cls, permission, self.user)


class ISerializedAttribute(interface.Interface):

    def bind(self, srlzrcls, attrname):
        pass

    def serialize(self, srlzr):
        pass

    def deserialize(self, srlzr):
        pass


class SerializedProperty(object):
    interface.implements(ISerializedAttribute)

    def __init__(self, read=None, write=None, scope=None, depth=1):
        self.read = read
        self.write = write
        self.scope = scope

        self.srlzrcls = None
        self.attrname = None

        self.__order__ = len(sys._getframe(depth).f_locals)

    def bind(self, srlzrcls, attrname):
        self.srlzrcls = srlzrcls
        self.attrname = attrname

        if not self.scope:
            self.scope = self.srlzrcls.resclass

        def procperm(name):
            value = getattr(self, name)
            if isinstance(value, basestring):
                value = permission(self.scope, value)
            setattr(self, name, value)

        procperm('read')
        procperm('write')

    def readperm(self, srlzr):
        return self.read and srlzr.has_permission(
            self.read.cls, self.read.permission)

    def writeperm(self, srlzr):
        return self.write and srlzr.has_permission(
            self.write.cls, self.write.permission)

    def getter(self, srlzr):
        return getattr(srlzr.obj, self.attrname)

    def setter(self, srlzr, value):
        setattr(srlzr.obj, self.attrname, value)

    def serialize(self, srlzr):
        if self.readperm(srlzr):
            srlzr.data[self.attrname] = self.getter(srlzr)

    def deserialize(self, srlzr):
        if self.writeperm(srlzr):
            self.setter(srlzr, srlzr.data[self.attrname])
        else:
            raise Forbidden("Attribute '%s' forbidden" % self.attrname)


class SerializedRelationship(SerializedProperty):

    def __init__(self, depth=1, **kwargs):
        super(SerializedRelationship, self).__init__(depth=depth + 1, **kwargs)

    def bind(self, srlzrcls, prop):
        super(SerializedRelationship, self).bind(srlzrcls, prop)
        self.relationship = srlzrcls.resclass.__mapper__ \
            .relationships[self.attrname]

    def getter(self, srlzr):
        value = super(SerializedRelationship, self).getter(srlzr)
        return dict(map(
            lambda k: (k.name, serval(getattr(value, k.name))),
            value.__mapper__.primary_key)) if value else None

    def setter(self, srlzr, value):
        mapper = self.relationship.mapper
        cls = mapper.class_

        obj = cls.filter_by(**dict(map(
            lambda k: (k.name, value[k.name]),
            mapper.primary_key))
        ).one()

        setattr(srlzr.obj, self.attrname, obj)


class SerializedResourceRelationship(SerializedRelationship):

    def getter(self, srlzr):
        value = SerializedProperty.getter(self, srlzr)
        return OrderedDict((
            ('id', value.id), ('parent', dict(id=value.parent_id))
        )) if value else None


class SerializerMeta(type):

    def __init__(cls, name, bases, nmspc):
        super(SerializerMeta, cls).__init__(name, bases, nmspc)

        proptab = []
        for prop, sp in nmspc.iteritems():
            if ISerializedAttribute.providedBy(sp):
                sp.bind(cls, prop)
                proptab.append((prop, sp))

        cls.proptab = sorted(proptab, cmp=lambda x, y: cmp(
            getattr(x[1], '__order__', sys.maxint),
            getattr(y[1], '__order__', sys.maxint)))

        if not nmspc.get('__abstract__', False):
            _registry.register(cls)


class Serializer(SerializerBase):
    __metaclass__ = SerializerMeta

    registry = _registry

    resclass = None

    def is_applicable(self):
        return self.resclass and isinstance(self.obj, self.resclass)

    def serialize(self):
        for prop, sp in self.proptab:
            sp.serialize(self)

    def deserialize(self):
        for prop, sp in self.proptab:
            if prop in self.data and not prop in self.keys:
                sp.deserialize(self)


class CompositeSerializer(SerializerBase):
    registry = _registry

    def __init__(self, obj, user, data=None):
        super(CompositeSerializer, self).__init__(obj, user, data)

        self.members = dict()
        for ident, mcls in self.registry._dict.iteritems():
            if data is None or ident in data:
                mdata = data[ident] if data else None
                mobj = mcls(obj, user, mdata)
                if mobj.is_applicable():
                    self.members[ident] = mobj

    def serialize(self):
        for ident, mobj in self.members.iteritems():
            mobj.serialize()
            self.data[ident] = mobj.data

    def deserialize(self):
        for ident, mobj in self.members.iteritems():
            if ident in self.data:
                mobj.deserialize()


def serval(value):
    if (
        value is None
        or isinstance(value, int)
        or isinstance(value, float)
        or isinstance(value, basestring)
    ):
        return value

    elif isinstance(value, dict):
        return dict(map(
            lambda k, v: (serval(k), serval(v)),
            value.iteritems()))

    elif isinstance(value, BaseClass):
        return dict(map(
            lambda k: (k.name, serval(getattr(value, k.name))),
            value.__mapper__.primary_key))

    elif hasattr(value, '__iter__'):
        return map(serval, value)

    else:
        raise NotImplementedError()
