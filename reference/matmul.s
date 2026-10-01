	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"matmul.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	blez	a2, .LBB0_7
# %bb.1:
	li	a3, 0
	mul	a4, a2, a2
	slli	a4, a4, 2
	add	a4, a0, a4
	slli	a5, a2, 2
.LBB0_2:                                # =>This Loop Header: Depth=1
                                        #     Child Loop BB0_3 Depth 2
                                        #       Child Loop BB0_4 Depth 3
	li	a6, 0
	mul	a7, a3, a2
	mv	t0, a4
.LBB0_3:                                #   Parent Loop BB0_2 Depth=1
                                        # =>  This Loop Header: Depth=2
                                        #       Child Loop BB0_4 Depth 3
	li	t1, 0
	mv	t2, a0
	mv	t3, t0
	mv	t4, a2
.LBB0_4:                                #   Parent Loop BB0_2 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        # =>    This Inner Loop Header: Depth=3
	lw	t5, 0(t2)
	lw	t6, 0(t3)
	mul	t5, t6, t5
	srai	t5, t5, 16
	add	t1, t5, t1
	addi	t4, t4, -1
	add	t3, t3, a5
	addi	t2, t2, 4
	bnez	t4, .LBB0_4
# %bb.5:                                #   in Loop: Header=BB0_3 Depth=2
	add	t2, a6, a7
	slli	t2, t2, 2
	add	t2, a1, t2
	sw	t1, 0(t2)
	addi	a6, a6, 1
	addi	t0, t0, 4
	bne	a6, a2, .LBB0_3
# %bb.6:                                #   in Loop: Header=BB0_2 Depth=1
	addi	a3, a3, 1
	add	a0, a0, a5
	bne	a3, a2, .LBB0_2
.LBB0_7:
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
