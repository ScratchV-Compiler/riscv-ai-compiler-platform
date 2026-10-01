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
	li	a2, 0
	li	a4, 256
.LBB0_1:                                # =>This Inner Loop Header: Depth=1
	add	a5, a0, a3
	lw	a5, 0(a5)
	addi	a3, a3, 4
	add	a2, a5, a2
	bne	a3, a4, .LBB0_1
# %bb.2:
	sw	a2, 0(a1)
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
