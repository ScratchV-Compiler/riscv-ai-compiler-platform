	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"add.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	li	a2, 0
	li	a3, 256
.LBB0_1:                                # =>This Inner Loop Header: Depth=1
	add	a4, a0, a2
	lw	a5, 0(a4)
	lw	a4, 256(a4)
	add	a4, a4, a5
	add	a5, a1, a2
	addi	a2, a2, 4
	sw	a4, 0(a5)
	bne	a2, a3, .LBB0_1
# %bb.2:
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
