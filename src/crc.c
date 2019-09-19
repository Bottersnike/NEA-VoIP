#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "stdint.h"


typedef struct {
    PyObject_HEAD

    int _size;
    int _polynomial;
    int table[256];
} CRCObject;

static int CRC_init(CRCObject *self, PyObject *args, PyObject *kwds) {
    static char *kwlist[] = {"size", "polynomial", NULL};

    const double exp = 0.9;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "kk", kwlist,
                                     &self->_size, &self->_polynomial))
        return -1;
    
    for (int i = 0; i < 256; i++) {
        int crc_accumulator = i << (self->_size - 8);

        for (int j = 0; j < 8; j++) {
            if (crc_accumulator & (1 << (self->_size - 1)))
                crc_accumulator = (crc_accumulator << 1) ^ self->_polynomial;
            else
                crc_accumulator = crc_accumulator << 1;
        }
        self->table[i] = crc_accumulator;
    }

    return 0;
}

static PyObject* CRC_call(CRCObject *self, PyObject *args, PyObject *kwds) {
    const char* data;
    Py_ssize_t dlen;
    int accumulator = 0;
    static char *kwlist[] = {"data", "accumulator", NULL};

    if (!PyArg_ParseTupleAndKeywords(args, kwds, "s#|k", kwlist,
                                     &data, &dlen, &accumulator))
        return NULL;

    for (int i = 0; i < dlen; i++) {
        int j = ((accumulator >> (self->_size - 8)) ^ data[i]) & 0xff;
        accumulator = ((accumulator << 8) ^ self->table[j]) & ((1 << self->_size) - 1);
    }

    char* data_out = PyMem_Malloc(2);
    data_out[0] = (uint8_t)(accumulator >> 8);
    data_out[1] = (uint8_t)(accumulator);
    return PyBytes_FromStringAndSize(data_out, 2);
}

static PyMethodDef CRC_methods[] = {
    {NULL}
};
static PyTypeObject CRCType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "crc.CRC",
    .tp_doc = "CRC object",
    .tp_basicsize = sizeof(CRCObject),
    .tp_itemsize = 0,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_new = PyType_GenericNew,

    .tp_init = (initproc) CRC_init,
    .tp_call = CRC_call,
    .tp_methods = CRC_methods,
};

static PyMethodDef ModuleMethods[] = {
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef crcmodule = {
    PyModuleDef_HEAD_INIT,
    .m_name = "crc",
    .m_doc = NULL,
    .m_size = -1,
    ModuleMethods
};

PyMODINIT_FUNC PyInit_crc(void) {
    PyObject *m;
    if (PyType_Ready(&CRCType) < 0)
        return NULL;

    m = PyModule_Create(&crcmodule);
    if (m == NULL)
        return NULL;

    Py_INCREF(&CRCType);
    PyModule_AddObject(m, "CRC", (PyObject *) &CRCType);
    return m;
}
