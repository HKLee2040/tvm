import tvm

def intrin_gemv(m, n):
    w = tvm.placeholder((m, n), name='w')
    x = tvm.placeholder((n,), name='x')
    k = tvm.reduce_axis((0, n), name='k')
    z = tvm.compute((m,), lambda i:
                    tvm.sum(w[i, k] * x[k], axis=k), name='z')
    Wb = tvm.decl_buffer(w.shape, w.dtype,
                         name="W",
                         offset_factor=16,
                         strides=[tvm.var('ldw'), 1])
    def intrin_func(ins, outs):
        ww, xx = ins
        zz = outs[0]
        ww_ptr = ww.access_ptr("r")
        xx_ptr = xx.access_ptr("r")
        zz_ptr = zz.access_ptr("w")
        body = tvm.call_packed(
            "gemv", ww_ptr, xx_ptr, zz_ptr, n, ww.strides[0])
        update = tvm.call_packed(
            "gemv_add", ww_ptr, xx_ptr, zz_ptr, n, ww.strides[0])
        return body, None, update

    with tvm.build_config(data_alignment=16,
                          offset_factor=16):
        return tvm.decl_tensor_intrin(z.op, intrin_func,
                                      binds={w: Wb})


def test_tensorize_matmul():
    n = 1024
    m = n
    l = n
    A = tvm.placeholder((n, l), name='A')
    B = tvm.placeholder((m, l), name='B')
    k = tvm.reduce_axis((0, l), name='k')
    C = tvm.compute((n, m), lambda i, j:
                    tvm.sum(B[j, k] * A[i, k], axis=k), name='C')

    def check(factor):
        s = tvm.create_schedule(C.op)
        x, y = C.op.axis
        yo, yi = s[C].split(y, factor=factor)
        gemv = intrin_gemv(factor, l)
        s[C].tensorize(yi, gemv)
        s = s.normalize()
        dom_map = tvm.schedule.InferBound(s)
        finfer = tvm.get_global_func("test.op.InferTensorizeRegion")
        out_dom, in_dom = finfer(s[C], dom_map)
        assert tvm.ir_pass.Equal(out_dom[x].extent, 1)
        assert tvm.ir_pass.Equal(out_dom[y].extent, factor)
        assert tvm.ir_pass.Equal(out_dom[y].min, yo * factor)
        fmatch = tvm.get_global_func("test.op.MatchTensorizeBody")
        body = fmatch(s[C], out_dom, in_dom, gemv)
        assert tvm.ir_pass.Equal(tvm.ir_pass.CanonicalSimplify(body[0]),
                                 tvm.ir_pass.CanonicalSimplify(gemv.op.body[0]))
        stmt = tvm.schedule.ScheduleOps(s, dom_map)
        tvm.lower(s, [A, B, C])


    def check_rfactor(factor, rfactor):
        s = tvm.create_schedule(C.op)
        x, y = C.op.axis
        rk = C.op.reduce_axis[0]
        yo, yi = s[C].split(y, factor=factor)
        ro, ri = s[C].split(rk, factor=rfactor)
        s[C].reorder(yo, ro, yi, ri)
        gemv = intrin_gemv(factor, rfactor)
        s[C].tensorize(yi, gemv)
        s = s.normalize()
        dom_map = tvm.schedule.InferBound(s)
        finfer = tvm.get_global_func("test.op.InferTensorizeRegion")
        out_dom, in_dom = finfer(s[C], dom_map)
        assert tvm.ir_pass.Equal(out_dom[x].extent, 1)
        assert tvm.ir_pass.Equal(out_dom[y].extent, factor)
        assert tvm.ir_pass.Equal(out_dom[y].min, yo * factor)
        fmatch = tvm.get_global_func("test.op.MatchTensorizeBody")
        body = fmatch(s[C], out_dom, in_dom, gemv)
        assert tvm.ir_pass.Equal(tvm.ir_pass.CanonicalSimplify(body[0]),
                                 tvm.ir_pass.CanonicalSimplify(gemv.op.body[0]))
        stmt = tvm.schedule.ScheduleOps(s, dom_map)
        tvm.lower(s, [A, B, C])

    check(16)
    check_rfactor(16, 16)


if __name__ == "__main__":
    test_tensorize_matmul()
