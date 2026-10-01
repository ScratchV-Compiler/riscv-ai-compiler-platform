	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"add.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	blez	a2, .LBB0_3
# %bb.1:
	slli	a3, a2, 2
.LBB0_2:                                # =>This Inner Loop Header: Depth=1
	lw	a4, 0(a0)
	add	a5, a0, a3
	lw	a5, 0(a5)
	add	a4, a5, a4
	sw	a4, 0(a1)
	addi	a2, a2, -1
	addi	a1, a1, 4
	addi	a0, a0, 4
	bnez	a2, .LBB0_2
.LBB0_3:
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
