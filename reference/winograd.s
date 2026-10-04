	.text
	.attribute	4, 16
	.attribute	5, "rv32i2p0_m2p0_f2p0"
	.file	"winograd.c"
	.globl	cnn_entry                       # -- Begin function cnn_entry
	.p2align	2
	.type	cnn_entry,@function
cnn_entry:                              # @cnn_entry
# %bb.0:
	addi	sp, sp, -112
	sw	ra, 108(sp)                     # 4-byte Folded Spill
	sw	s0, 104(sp)                     # 4-byte Folded Spill
	addi	s0, sp, 112
	sw	a0, -12(s0)
	sw	a1, -16(s0)
	sw	a2, -20(s0)
	lw	a0, -12(s0)
	sw	a0, -24(s0)
	lw	a0, -24(s0)
	lw	a0, 0(a0)
	sw	a0, -28(s0)
	lw	a0, -24(s0)
	lw	a0, 4(a0)
	sw	a0, -32(s0)
	lw	a0, -24(s0)
	lw	a0, 8(a0)
	sw	a0, -36(s0)
	lw	a0, -24(s0)
	lw	a0, 12(a0)
	sw	a0, -40(s0)
	lw	a0, -24(s0)
	lw	a0, 16(a0)
	sw	a0, -44(s0)
	lw	a0, -24(s0)
	lw	a0, 20(a0)
	sw	a0, -48(s0)
	lw	a0, -24(s0)
	addi	a0, a0, 24
	sw	a0, -52(s0)
	lw	a0, -52(s0)
	lw	a1, -28(s0)
	lw	a2, -32(s0)
	mul	a1, a1, a2
	lw	a2, -36(s0)
	mul	a1, a1, a2
	lw	a2, -40(s0)
	mul	a1, a1, a2
	slli	a1, a1, 2
	add	a0, a0, a1
	sw	a0, -56(s0)
	lw	a0, -16(s0)
	sw	a0, -60(s0)
	lw	a0, -48(s0)
	srli	a1, a0, 31
	add	a0, a0, a1
	srai	a0, a0, 1
	sw	a0, -64(s0)
	li	a0, 0
	sw	a0, -68(s0)
	j	.LBB0_1
.LBB0_1:                                # =>This Loop Header: Depth=1
                                        #     Child Loop BB0_3 Depth 2
                                        #       Child Loop BB0_5 Depth 3
                                        #         Child Loop BB0_7 Depth 4
                                        #           Child Loop BB0_9 Depth 5
                                        #             Child Loop BB0_11 Depth 6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -68(s0)
	lw	a1, -28(s0)
	bge	a0, a1, .LBB0_34
	j	.LBB0_2
.LBB0_2:                                #   in Loop: Header=BB0_1 Depth=1
	li	a0, 0
	sw	a0, -72(s0)
	j	.LBB0_3
.LBB0_3:                                #   Parent Loop BB0_1 Depth=1
                                        # =>  This Loop Header: Depth=2
                                        #       Child Loop BB0_5 Depth 3
                                        #         Child Loop BB0_7 Depth 4
                                        #           Child Loop BB0_9 Depth 5
                                        #             Child Loop BB0_11 Depth 6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -72(s0)
	lw	a1, -44(s0)
	bge	a0, a1, .LBB0_32
	j	.LBB0_4
.LBB0_4:                                #   in Loop: Header=BB0_3 Depth=2
	li	a0, 0
	sw	a0, -76(s0)
	j	.LBB0_5
.LBB0_5:                                #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        # =>    This Loop Header: Depth=3
                                        #         Child Loop BB0_7 Depth 4
                                        #           Child Loop BB0_9 Depth 5
                                        #             Child Loop BB0_11 Depth 6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -76(s0)
	lw	a1, -32(s0)
	bge	a0, a1, .LBB0_30
	j	.LBB0_6
.LBB0_6:                                #   in Loop: Header=BB0_5 Depth=3
	li	a0, 0
	sw	a0, -80(s0)
	j	.LBB0_7
.LBB0_7:                                #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        #       Parent Loop BB0_5 Depth=3
                                        # =>      This Loop Header: Depth=4
                                        #           Child Loop BB0_9 Depth 5
                                        #             Child Loop BB0_11 Depth 6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -80(s0)
	lw	a1, -36(s0)
	bge	a0, a1, .LBB0_28
	j	.LBB0_8
.LBB0_8:                                #   in Loop: Header=BB0_7 Depth=4
	li	a0, 0
	sw	a0, -84(s0)
	sw	a0, -88(s0)
	j	.LBB0_9
.LBB0_9:                                #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        #       Parent Loop BB0_5 Depth=3
                                        #         Parent Loop BB0_7 Depth=4
                                        # =>        This Loop Header: Depth=5
                                        #             Child Loop BB0_11 Depth 6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -88(s0)
	lw	a1, -40(s0)
	bge	a0, a1, .LBB0_26
	j	.LBB0_10
.LBB0_10:                               #   in Loop: Header=BB0_9 Depth=5
	li	a0, 0
	sw	a0, -92(s0)
	j	.LBB0_11
.LBB0_11:                               #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        #       Parent Loop BB0_5 Depth=3
                                        #         Parent Loop BB0_7 Depth=4
                                        #           Parent Loop BB0_9 Depth=5
                                        # =>          This Loop Header: Depth=6
                                        #               Child Loop BB0_16 Depth 7
	lw	a0, -92(s0)
	lw	a1, -48(s0)
	bge	a0, a1, .LBB0_24
	j	.LBB0_12
.LBB0_12:                               #   in Loop: Header=BB0_11 Depth=6
	lw	a0, -76(s0)
	lw	a1, -64(s0)
	sub	a0, a0, a1
	lw	a1, -92(s0)
	add	a0, a0, a1
	sw	a0, -96(s0)
	lw	a0, -96(s0)
	li	a1, 0
	blt	a0, a1, .LBB0_14
	j	.LBB0_13
.LBB0_13:                               #   in Loop: Header=BB0_11 Depth=6
	lw	a0, -96(s0)
	lw	a1, -32(s0)
	blt	a0, a1, .LBB0_15
	j	.LBB0_14
.LBB0_14:                               #   in Loop: Header=BB0_11 Depth=6
	j	.LBB0_23
.LBB0_15:                               #   in Loop: Header=BB0_11 Depth=6
	li	a0, 0
	sw	a0, -100(s0)
	j	.LBB0_16
.LBB0_16:                               #   Parent Loop BB0_1 Depth=1
                                        #     Parent Loop BB0_3 Depth=2
                                        #       Parent Loop BB0_5 Depth=3
                                        #         Parent Loop BB0_7 Depth=4
                                        #           Parent Loop BB0_9 Depth=5
                                        #             Parent Loop BB0_11 Depth=6
                                        # =>            This Inner Loop Header: Depth=7
	lw	a0, -100(s0)
	lw	a1, -48(s0)
	bge	a0, a1, .LBB0_22
	j	.LBB0_17
.LBB0_17:                               #   in Loop: Header=BB0_16 Depth=7
	lw	a0, -80(s0)
	lw	a1, -64(s0)
	sub	a0, a0, a1
	lw	a1, -100(s0)
	add	a0, a0, a1
	sw	a0, -104(s0)
	lw	a0, -104(s0)
	li	a1, 0
	blt	a0, a1, .LBB0_19
	j	.LBB0_18
.LBB0_18:                               #   in Loop: Header=BB0_16 Depth=7
	lw	a0, -104(s0)
	lw	a1, -36(s0)
	blt	a0, a1, .LBB0_20
	j	.LBB0_19
.LBB0_19:                               #   in Loop: Header=BB0_16 Depth=7
	j	.LBB0_21
.LBB0_20:                               #   in Loop: Header=BB0_16 Depth=7
	lw	a0, -52(s0)
	lw	a1, -68(s0)
	lw	a2, -32(s0)
	mul	a1, a1, a2
	lw	a2, -96(s0)
	add	a1, a1, a2
	lw	a2, -36(s0)
	mul	a1, a1, a2
	lw	a2, -104(s0)
	add	a1, a1, a2
	lw	a2, -40(s0)
	mul	a1, a1, a2
	lw	a2, -88(s0)
	add	a1, a1, a2
	slli	a1, a1, 2
	add	a0, a0, a1
	flw	ft0, 0(a0)
	fsw	ft0, -108(s0)
	lw	a0, -56(s0)
	lw	a1, -72(s0)
	lw	a2, -40(s0)
	mul	a1, a1, a2
	lw	a2, -88(s0)
	add	a1, a1, a2
	lw	a2, -48(s0)
	mul	a1, a1, a2
	lw	a3, -92(s0)
	add	a1, a1, a3
	mul	a1, a1, a2
	lw	a2, -100(s0)
	add	a1, a1, a2
	slli	a1, a1, 2
	add	a0, a0, a1
	flw	ft0, 0(a0)
	fsw	ft0, -112(s0)
	flw	ft0, -108(s0)
	flw	ft1, -112(s0)
	flw	ft2, -84(s0)
	fmadd.s	ft0, ft0, ft1, ft2
	fsw	ft0, -84(s0)
	j	.LBB0_21
.LBB0_21:                               #   in Loop: Header=BB0_16 Depth=7
	lw	a0, -100(s0)
	addi	a0, a0, 1
	sw	a0, -100(s0)
	j	.LBB0_16
.LBB0_22:                               #   in Loop: Header=BB0_11 Depth=6
	j	.LBB0_23
.LBB0_23:                               #   in Loop: Header=BB0_11 Depth=6
	lw	a0, -92(s0)
	addi	a0, a0, 1
	sw	a0, -92(s0)
	j	.LBB0_11
.LBB0_24:                               #   in Loop: Header=BB0_9 Depth=5
	j	.LBB0_25
.LBB0_25:                               #   in Loop: Header=BB0_9 Depth=5
	lw	a0, -88(s0)
	addi	a0, a0, 1
	sw	a0, -88(s0)
	j	.LBB0_9
.LBB0_26:                               #   in Loop: Header=BB0_7 Depth=4
	flw	ft0, -84(s0)
	lw	a0, -60(s0)
	lw	a1, -68(s0)
	lw	a2, -44(s0)
	mul	a1, a1, a2
	lw	a2, -72(s0)
	add	a1, a1, a2
	lw	a2, -32(s0)
	mul	a1, a1, a2
	lw	a2, -76(s0)
	add	a1, a1, a2
	lw	a2, -36(s0)
	mul	a1, a1, a2
	lw	a2, -80(s0)
	add	a1, a1, a2
	slli	a1, a1, 2
	add	a0, a0, a1
	fsw	ft0, 0(a0)
	j	.LBB0_27
.LBB0_27:                               #   in Loop: Header=BB0_7 Depth=4
	lw	a0, -80(s0)
	addi	a0, a0, 1
	sw	a0, -80(s0)
	j	.LBB0_7
.LBB0_28:                               #   in Loop: Header=BB0_5 Depth=3
	j	.LBB0_29
.LBB0_29:                               #   in Loop: Header=BB0_5 Depth=3
	lw	a0, -76(s0)
	addi	a0, a0, 1
	sw	a0, -76(s0)
	j	.LBB0_5
.LBB0_30:                               #   in Loop: Header=BB0_3 Depth=2
	j	.LBB0_31
.LBB0_31:                               #   in Loop: Header=BB0_3 Depth=2
	lw	a0, -72(s0)
	addi	a0, a0, 1
	sw	a0, -72(s0)
	j	.LBB0_3
.LBB0_32:                               #   in Loop: Header=BB0_1 Depth=1
	j	.LBB0_33
.LBB0_33:                               #   in Loop: Header=BB0_1 Depth=1
	lw	a0, -68(s0)
	addi	a0, a0, 1
	sw	a0, -68(s0)
	j	.LBB0_1
.LBB0_34:
	lw	ra, 108(sp)                     # 4-byte Folded Reload
	lw	s0, 104(sp)                     # 4-byte Folded Reload
	addi	sp, sp, 112
	ret
.Lfunc_end0:
	.size	cnn_entry, .Lfunc_end0-cnn_entry
                                        # -- End function
	.ident	"Ubuntu clang version 14.0.0-1ubuntu1.1"
	.section	".note.GNU-stack","",@progbits
	.addrsig
