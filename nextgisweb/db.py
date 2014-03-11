# -*- coding: utf-8 -*-
from sqlalchemy import *                    # NOQA
from sqlalchemy.orm import *                # NOQA
from sqlalchemy.ext.declarative import *    # NOQA

from sqlalchemy import event                # NOQA
from sqlalchemy import sql                  # NOQA
from sqlalchemy import func                 # NOQA

from sqlalchemy import Enum as _Enum


class Enum(_Enum):
    """ Обертка sqlalchemy.Enum с предустановленным native_enum=False """

    def __init__(self, *args, **kwargs):
        if 'native_enum' in kwargs:
            assert kwargs['native_enum'] is False
        else:
            kwargs['native_enum'] = False
        super(Enum, self).__init__(*args, **kwargs)
