	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"matmul.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	li	a2, 0
	addi	a1, a1, 8
	addi	a3, a0, 8
	li	a4, 64
.LBB0_1:                                # =>This Inner Loop Header: Depth=1
	add	a5, a3, a2
	lw	a6, -8(a5)
	lw	a7, 64(a0)
	lw	t0, -4(a5)
	lw	t1, 80(a0)
	mul	a6, a7, a6
	srai	a6, a6, 16
	mul	a7, t1, t0
	srai	a7, a7, 16
	lw	t0, 0(a5)
	lw	t1, 96(a0)
	add	a6, a7, a6
	lw	a7, 4(a5)
	lw	t2, 112(a0)
	mul	t0, t1, t0
	srai	t0, t0, 16
	add	a6, t0, a6
	mul	a7, t2, a7
	srai	a7, a7, 16
	add	a7, a7, a6
	add	a6, a1, a2
	sw	a7, -8(a6)
	lw	a7, -8(a5)
	lw	t0, 68(a0)
	lw	t1, -4(a5)
	lw	t2, 84(a0)
	mul	a7, t0, a7
	srai	a7, a7, 16
	mul	t0, t2, t1
	srai	t0, t0, 16
	lw	t1, 0(a5)
	lw	t2, 100(a0)
	add	a7, t0, a7
	lw	t0, 4(a5)
	lw	t3, 116(a0)
	mul	t1, t2, t1
	srai	t1, t1, 16
	add	a7, t1, a7
	mul	t0, t3, t0
	srai	t0, t0, 16
	add	a7, t0, a7
	sw	a7, -4(a6)
	lw	a7, -8(a5)
	lw	t0, 72(a0)
	lw	t1, -4(a5)
	lw	t2, 88(a0)
	mul	a7, t0, a7
	srai	a7, a7, 16
	mul	t0, t2, t1
	srai	t0, t0, 16
	lw	t1, 0(a5)
	lw	t2, 104(a0)
	add	a7, t0, a7
	lw	t0, 4(a5)
	lw	t3, 120(a0)
	mul	t1, t2, t1
	srai	t1, t1, 16
	add	a7, t1, a7
	mul	t0, t3, t0
	srai	t0, t0, 16
	add	a7, t0, a7
	sw	a7, 0(a6)
	lw	a7, -8(a5)
	lw	t0, 76(a0)
	lw	t1, -4(a5)
	lw	t2, 92(a0)
	mul	a7, t0, a7
	srai	a7, a7, 16
	mul	t0, t2, t1
	srai	t0, t0, 16
	lw	t1, 0(a5)
	lw	t2, 108(a0)
	add	a7, t0, a7
	lw	a5, 4(a5)
	lw	t0, 124(a0)
	mul	t1, t2, t1
	srai	t1, t1, 16
	add	a7, t1, a7
	mul	a5, t0, a5
	srai	a5, a5, 16
	add	a5, a5, a7
	addi	a2, a2, 16
	sw	a5, 4(a6)
	bne	a2, a4, .LBB0_1
# %bb.2:
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
