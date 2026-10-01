	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"reducesum.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	li	a3, 0
	blez	a2, .LBB0_2
.LBB0_1:                                # =>This Inner Loop Header: Depth=1
	lw	a4, 0(a0)
	add	a3, a4, a3
	addi	a2, a2, -1
	addi	a0, a0, 4
	bnez	a2, .LBB0_1
.LBB0_2:
	sw	a3, 0(a1)
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
