#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "stdint.h"
#include "stdio.h"

typedef struct {
    PyObject_HEAD

    double gain;
    double amp;
    double _mig;
    double _mag;
    unsigned int _frame;

    unsigned long attack;
    unsigned long release;
    unsigned long threshold;
    double exp;
    unsigned int _c_start;
    unsigned int _c_end;
} CompressorObject;

static int Compressor_init(CompressorObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"attack", "release", "threshold", "exp", NULL};

    const double exp = 0.9;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "kkk|d", kwlist,
                                     &self->attack, &self->release,
                                     &self->threshold, &exp))
        return -1;

    self->gain = 1;
    self->amp = 0;
    self->_mig = 0;
    self->_mag = 0;
    self->_frame = 0;
    self->_c_start = 0;
    self->_c_end = 0;

    self->exp = exp;

    return 0;
}

static PyObject* Compressor_feed(CompressorObject *self, PyObject *args) {
    const char* data;
    Py_ssize_t dlen;
    if (!PyArg_ParseTuple(args, "s#", &data, &dlen))
        return NULL;

    char* data_out = PyMem_Malloc(dlen);

    for (int i = 0; i < dlen; i += 2) {
        int16_t frame_s = (int16_t)((uint8_t)data[i] | (uint8_t)data[i + 1] << 8);
        self->_frame++;
        double frame = (double)frame_s;
        self->amp = ((frame < 0 ? -frame : frame) * self->exp) + (1. - self->exp) * self->amp;

        if (self->amp * self->gain < self->threshold) {
            if (self->_c_start == 0) {
                self->_mag = self->gain;
                self->_c_start = self->_frame;
                self->_c_end = 0;
            }
            self->gain = self->_mig + (double)(self->_frame - self->_c_start) / self->release;
            if (self->gain > 1)
                self->gain = 1.;
            if (self->gain > self->_mag)
                self->_mag = self->gain;
        } else {
            if (self->_c_end == 0) {
                self->_mig = self->gain;
                self->_mag = 1. - self->_mag;
                self->_c_end = self->_frame;
                self->_c_start = 0;
            }
            self->gain = 1. - (double)(self->_frame - self->_c_end) / self->attack - self->_mag;
            if (self->gain < 0)
                self->gain = 0.;
            if (self->_mig > self->gain)
                self->_mig = self->gain;
        }

        data_out[i] = (uint8_t)((int16_t)(frame_s * self->gain) >> 0);
        data_out[i + 1] = (uint8_t)((int16_t)(frame_s * self->gain) >> 8);
    }

    PyObject *result = PyBytes_FromStringAndSize(data_out, dlen);
    PyMem_Free(data_out);
    return result;
}

static PyObject* Compressor_get_attack(CompressorObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->attack);
}
static int Compressor_set_attack(CompressorObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Attack must be an integer");
        return -1;
    }
    self->attack = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyObject* Compressor_get_release(CompressorObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->release);
}
static int Compressor_set_release(CompressorObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Release must be an integer");
        return -1;
    }
    self->release = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyObject* Compressor_get_threshold(CompressorObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->threshold);
}
static int Compressor_set_threshold(CompressorObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Threshold must be an integer");
        return -1;
    }
    self->threshold = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyGetSetDef Compressor_getsetters[] = {
    {"attack", (getter) Compressor_get_attack, (setter) Compressor_set_attack, "", NULL},
    {"release", (getter) Compressor_get_release, (setter) Compressor_set_release, "", NULL},
    {"threshold", (getter) Compressor_get_threshold, (setter) Compressor_set_threshold, "", NULL},
    {NULL}
};
static PyMethodDef Compressor_methods[] = {
    {"feed", (PyCFunction) Compressor_feed, METH_VARARGS, ""},
    {NULL}
};
static PyTypeObject CompressorType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "audio.Compressor",
    .tp_doc = "Compressor object",
    .tp_basicsize = sizeof(CompressorObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,

    .tp_init = (initproc) Compressor_init,
    .tp_methods = Compressor_methods,
    .tp_getset = Compressor_getsetters,
};

typedef struct {
    PyObject_HEAD

    double gain;
    double amp;
    double _mig;
    double _mag;
    unsigned int _frame;

    unsigned long attack;
    unsigned long hold;
    unsigned long release;
    unsigned long threshold;
    double exp;
    unsigned int _c_start;
    unsigned int _c_end;
} GateObject;

static int Gate_init(GateObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"attack", "hold", "release", "threshold", "exp", NULL};

    const double exp = 0.9;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "kkkk|d", kwlist,
                                     &self->attack, &self->hold,
                                     &self->release, &self->threshold,
                                     &exp))
        return -1;

    self->gain = 1;
    self->amp = 0;
    self->_mig = 0;
    self->_mag = 0;
    self->_frame = 0;
    self->_c_start = 0;
    self->_c_end = 0;

    self->exp = exp;

    return 0;
}

static PyObject* Gate_feed(GateObject *self, PyObject *args) {
    const char* data;
    Py_ssize_t dlen;
    if (!PyArg_ParseTuple(args, "s#", &data, &dlen))
        return NULL;

    char* data_out = PyMem_Malloc(dlen);

    for (int i = 0; i < dlen; i += 2) {
        int16_t frame_s = (int16_t)((uint8_t)data[i] | (uint8_t)data[i + 1] << 8);
        self->_frame++;
        double frame = (double)frame_s;
        self->amp = ((frame < 0 ? -frame : frame) * self->exp) + (1. - self->exp) * self->amp;

        if (self->amp > self->threshold) {
            if (self->_c_start == 0) {
                self->_mag = self->gain;
                self->_c_start = self->_frame;
                self->_c_end = 0;
            }
            self->gain = self->_mig + (double)(self->_frame - self->_c_start) / self->attack;
            if (self->gain > 1)
                self->gain = 1.;
            if (self->gain > self->_mag)
                self->_mag = self->gain;
        } else {
            if (self->_c_end == 0) {
                self->_mig = self->gain;
                self->_mag = 1. - self->_mag;
                self->_c_end = self->_frame;
                self->_c_start = 0;
            }
            if (self->_frame - self->_c_end >= self->hold) {
                self->gain = 1. - (double)(self->_frame - self->_c_end - self->hold) / self->release - self->_mag;
                if (self->gain < 0)
                    self->gain = 0.;
            }
            if (self->_mig > self->gain)
                self->_mig = self->gain;
        }

        data_out[i] = (uint8_t)((int16_t)(frame_s * self->gain) >> 0);
        data_out[i + 1] = (uint8_t)((int16_t)(frame_s * self->gain) >> 8);
    }

    PyObject *result = PyBytes_FromStringAndSize(data_out, dlen);
    PyMem_Free(data_out);
    return result;
}

static PyObject* Gate_get_attack(GateObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->attack);
}
static int Gate_set_attack(GateObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Attack must be an integer");
        return -1;
    }
    self->attack = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyObject* Gate_get_hold(GateObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->hold);
}
static int Gate_set_hold(GateObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Hold must be an integer");
        return -1;
    }
    self->hold = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyObject* Gate_get_release(GateObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->release);
}
static int Gate_set_release(GateObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Release must be an integer");
        return -1;
    }
    self->release = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyObject* Gate_get_threshold(GateObject *self, void *closure) {
    return PyLong_FromUnsignedLong(self->threshold);
}
static int Gate_set_threshold(GateObject *self, PyObject *value, void *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete this attribute");
        return -1;
    }
    if (!PyLong_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "Threshold must be an integer");
        return -1;
    }

    self->threshold = PyLong_AsUnsignedLong(value);
    return 0;
}

static PyGetSetDef Gate_getsetters[] = {
    {"attack", (getter) Gate_get_attack, (setter) Gate_set_attack, "", NULL},
    {"hold", (getter) Gate_get_hold, (setter) Gate_set_hold, "", NULL},
    {"release", (getter) Gate_get_release, (setter) Gate_set_release, "", NULL},
    {"threshold", (getter) Gate_get_threshold, (setter) Gate_set_threshold, "", NULL},
    {NULL}
};
static PyMethodDef Gate_methods[] = {
    {"feed", (PyCFunction) Gate_feed, METH_VARARGS, ""},
    {NULL}
};
static PyTypeObject GateType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "audio.Gate",
    .tp_doc = "Gate object",
    .tp_basicsize = sizeof(GateObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,

    .tp_init = (initproc) Gate_init,
    .tp_methods = Gate_methods,
    .tp_getset = Gate_getsetters,
};


static PyMethodDef ModuleMethods[] = {
    // {"system",  spam_system, METH_VARARGS, "Execute a shell command."},

    {NULL, NULL, 0, NULL}
};


static struct PyModuleDef audiomodule = {
    PyModuleDef_HEAD_INIT,
    .m_name = "audio",
    .m_doc = NULL,
    .m_size = -1,
    ModuleMethods
};

PyMODINIT_FUNC PyInit_audio(void) {
    PyObject *m;
    if (PyType_Ready(&GateType) < 0)
        return NULL;
    if (PyType_Ready(&CompressorType) < 0)
        return NULL;

    m = PyModule_Create(&audiomodule);
    if (m == NULL)
        return NULL;

    Py_INCREF(&GateType);
    PyModule_AddObject(m, "Gate", (PyObject *) &GateType);
    Py_INCREF(&CompressorType);
    PyModule_AddObject(m, "Compressor", (PyObject *) &CompressorType);
    return m;
}
