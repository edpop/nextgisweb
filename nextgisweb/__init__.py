# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, absolute_import
import os
import codecs
from ConfigParser import RawConfigParser

from pyramid.config import Configurator
from pyramid.paster import setup_logging
from pyramid.authentication import AuthTktAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy

from sqlalchemy import engine_from_config

from .models import (
    DBSession,
    Base,
)

from .component import Component, load_all
from .env import Env, setenv


def pkginfo():
    components = (
        'core',
        'pyramid',
        'auth',
        'resource',
        'resmeta',
        'spatial_ref_sys',
        'layer',
        'feature_layer',
        'feature_description',
        'feature_attachment',
        'render',
        'marker_library',
        'webmap',
        'file_storage',
        'vector_layer',
        'postgis',
        'raster_layer',
        'raster_style',
        'wmsclient',
        'wmsserver',
        'wfsserver',
        'file_upload',
    )

    return dict(
        components=dict(map(
            lambda (i): (i, "nextgisweb.%s" % i),
            components)
        )
    )


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application. """

    if 'logging' in settings:
        setup_logging(settings['logging'])

    cfg = RawConfigParser()
    cfg.readfp(codecs.open(settings['config'], 'r', 'utf-8'))

    for section in cfg.sections():
        for item, value in cfg.items(section):
            cfg.set(section, item, value % os.environ)

    env = Env(cfg)
    env.initialize()

    setenv(env)

    config = env.pyramid.make_app(settings)
    return config.make_wsgi_app()


def amd_packages():
    return (
        # contrib packages
        ('dojo', 'nextgisweb:amd_packages/contrib/dojo'),
        ('dijit', 'nextgisweb:amd_packages/contrib/dijit'),
        ('dojox', 'nextgisweb:amd_packages/contrib/dojox'),
        ('cbtree', 'nextgisweb:amd_packages/contrib/cbtree'),
        ('xstyle', 'nextgisweb:amd_packages/contrib/xstyle'),
        ('put-selector', 'nextgisweb:amd_packages/contrib/put-selector'),
        ('dgrid', 'nextgisweb:amd_packages/contrib/dgrid'),
        ('handlebars', 'nextgisweb:amd_packages/contrib/handlebars'),
        ('openlayers', 'nextgisweb:amd_packages/contrib/openlayers'),
        ('dom-to-image', 'nextgisweb:amd_packages/contrib/dom-to-image'),
        ('svg4everybody', 'nextgisweb:amd_packages/contrib/svg4everybody'),
        ('codemirror', 'nextgisweb:amd_packages/contrib/codemirror'),
        ('jquery', 'nextgisweb:amd_packages/contrib/jquery'),

        # nextgisweb packages
        ('ngw', 'nextgisweb:amd_packages/ngw'),

        # components packages
        ('ngw-pyramid', 'nextgisweb:pyramid/amd/ngw-pyramid'),
        ('ngw-resource', 'nextgisweb:resource/amd/ngw-resource'),
        ('ngw-resmeta', 'nextgisweb:resmeta/amd/ngw-resmeta'),
        ('ngw-feature-layer', 'nextgisweb:feature_layer/amd/ngw-feature-layer'),
        ('ngw-feature-description', 'nextgisweb:feature_description/amd/ngw-feature-description'),
        ('ngw-feature-attachment', 'nextgisweb:feature_attachment/amd/ngw-feature-attachment'),
        ('ngw-postgis', 'nextgisweb:postgis/amd/ngw-postgis'),
        ('ngw-wmsclient', 'nextgisweb:wmsclient/amd/ngw-wmsclient'),
        ('ngw-wmsserver', 'nextgisweb:wmsserver/amd/ngw-wmsserver'),
        ('ngw-wfsserver', 'nextgisweb:wfsserver/amd/ngw-wfsserver'),
        ('ngw-vector-layer', 'nextgisweb:vector_layer/amd/ngw-vector-layer'),
        ('ngw-raster-layer', 'nextgisweb:raster_layer/amd/ngw-raster-layer'),
        ('ngw-webmap', 'nextgisweb:webmap/amd/ngw-webmap'),
        ('ngw-auth', 'nextgisweb:auth/amd/ngw-auth'),
        ('ngw-file-upload', 'nextgisweb:file_upload/amd/ngw-file-upload'),
        ('ngw-spatial-ref-sys', 'nextgisweb:spatial_ref_sys/amd/ngw-spatial-ref-sys'),
        ('ngw-render', 'nextgisweb:render/amd/ngw-render'),
    )
