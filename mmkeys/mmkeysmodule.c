/* Copyright 2004 Joe Wreschnig. Released under the terms of the GNU GPL. */

#include <pygobject.h>

void mmkeys__register_classes(PyObject *d);

extern PyMethodDef mmkeys__functions[];

DL_EXPORT(void) initmmkeys_(void) {
    PyObject *m, *d;

    init_pygobject();

    m = Py_InitModule("mmkeys_", mmkeys__functions);
    d = PyModule_GetDict(m);

    mmkeys__register_classes(d);

    if (PyErr_Occurred()) Py_FatalError("can't initialise module mmkeys");
}
