	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0"
	.file	"matmul.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	addi	sp, sp, -48
	sw	ra, 44(sp)                      # 4-byte Folded Spill
	sw	s0, 40(sp)                      # 4-byte Folded Spill
	addi	s0, sp, 48
	sw	a0, -12(s0)
	sw	a1, -16(s0)
	sw	a2, -20(s0)
	lw	a0, -12(s0)
	sw	a0, -24(s0)
	lw	a0, -12(s0)
	lw	a1, -20(s0)
	mul	a1, a1, a1
	slli	a1, a1, 2
	add	a0, a0, a1
	sw	a0, -28(s0)
	li	a0, 0
	sw	a0, -32(s0)
	j	.LBB0_1
.LBB0_1:                                # =>This Loop Header: Depth=1
                                        #     Child Loop BB0_3 Depth 2
                                        #       Child Loop BB0_5 Depth 3
	lw	a0, -32(s0)
	lw	a1, -20(s0)
	bge	a0, a1, .LBB0_12
	j	.LBB0_2
.LBB0_2:                                #   in Loop: Header=BB0_1 Depth=1
	li	a0, 0
	sw	a0, -36(s0)
	j	.LBB0_3
.LBB0_3:                                #   Parent Loop BB0_1 Depth=1
                                        # =>  This Loop Header: Depth=2
                                        #       Child Loop BB0_5 Depth 3
	lw	a0, -36(s0)
	lw	a1, -20(s0)
	bge	a0, a1, .LBB0_10
	j	.LBB0_4
.LBB0_4:                                #   in Loop: Header=BB0_3 Depth=2
	li	a0, 0
	sw	a0, -40(s0)
	sw	a0, -44(s0)
	j	.LBB0_5
.LBB0_5:                                #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        # =>    This Inner Loop Header: Depth=3
	lw	a0, -44(s0)
	lw	a1, -20(s0)
	bge	a0, a1, .LBB0_8
	j	.LBB0_6
.LBB0_6:                                #   in Loop: Header=BB0_5 Depth=3
	lw	a0, -24(s0)
	lw	a1, -32(s0)
	lw	a3, -20(s0)
	mul	a1, a1, a3
	lw	a2, -44(s0)
	add	a1, a1, a2
	slli	a1, a1, 2
	add	a0, a0, a1
	lw	a0, 0(a0)
	lw	a1, -28(s0)
	mul	a2, a2, a3
	lw	a3, -36(s0)
	add	a2, a2, a3
	slli	a2, a2, 2
	add	a1, a1, a2
	lw	a1, 0(a1)
	mul	a0, a0, a1
	srai	a1, a0, 16
	lw	a0, -40(s0)
	add	a0, a0, a1
	sw	a0, -40(s0)
	j	.LBB0_7
.LBB0_7:                                #   in Loop: Header=BB0_5 Depth=3
	lw	a0, -44(s0)
	addi	a0, a0, 1
	sw	a0, -44(s0)
	j	.LBB0_5
.LBB0_8:                                #   in Loop: Header=BB0_3 Depth=2
	lw	a0, -40(s0)
	lw	a1, -16(s0)
	lw	a2, -32(s0)
	lw	a3, -20(s0)
	mul	a2, a2, a3
	lw	a3, -36(s0)
	add	a2, a2, a3
	slli	a2, a2, 2
	add	a1, a1, a2
	sw	a0, 0(a1)
	j	.LBB0_9
.LBB0_9:                                #   in Loop: Header=BB0_3 Depth=2
	lw	a0, -36(s0)
	addi	a0, a0, 1
	sw	a0, -36(s0)
	j	.LBB0_3
.LBB0_10:                               #   in Loop: Header=BB0_1 Depth=1
	j	.LBB0_11
.LBB0_11:                               #   in Loop: Header=BB0_1 Depth=1
	lw	a0, -32(s0)
	addi	a0, a0, 1
	sw	a0, -32(s0)
	j	.LBB0_1
.LBB0_12:
	lw	ra, 44(sp)                      # 4-byte Folded Reload
	lw	s0, 40(sp)                      # 4-byte Folded Reload
	addi	sp, sp, 48
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
