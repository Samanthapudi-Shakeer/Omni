/************************************************************************//**
 *
 *  @file		Blocks.cpp
 *  @brief		Blocks class source file.
 *
 ***************************************************************************/

/*******************************************************************************
 * INCLUDE定義
 *******************************************************************************/ /* [EN] Include definitions */
#include "CommandInterface.hpp"
#include "Disk.hpp"
#include "DriveParameter.hpp"
#include "SenseData.hpp"
#include "SystemService.hpp"
#include "Log.hpp"
#include "Utility.hpp"
#include "Debug.hpp"
#include "Blocks.hpp"

//#define ENABLE_GEOMETRY_MONITER


/* Initialize extern object pointer */
Blocks* pBlocks = NULL;


/*******************************************************************************
 * 定数データ定義
 *******************************************************************************/ /* [EN] Constant data definitions */
const uint8_t klSizeOfBlockDescriptor     = 0x18;	/**< Block DescriptorのByte数 */ /* [EN] Block DescriptorのByte数 */
const uint8_t klSizeOfModeParameterPage03 = 0x20;	/**< Mode Parameter Page03のByte数 */ /* [EN] Mode Parameter Page03のByte数 */
const uint8_t klSizeOfDiskSectorFormat    = 0x14;	/**< Disk Sector FormatのByte数 */ /* [EN] Disk Sector Format byte count */


/*
 * Class "Blocks" member functions
 */
/*--------------------------------------------------------------------------------
 * Constructor
 *------------------------------------------------------------------------------*/
Blocks::Blocks()
{
	pPage0 = NULL;
	pPage6 = NULL;
	#if !defined Switch_NotSupportedAreaSkip
	pPage12Cmr = NULL;
	#if defined Switch_Hybrid
	pPage12Smr = NULL;
	#endif
	#endif
	mMaxCylNumH = 0;
	mMaxCylNumL = 0;
	mStandardSPT = 1;	/* 除数になりうる為、'1' */ /* [EN] To avoid division by zero, '1' */
	mSTWCylModeF = false;
	memset(mMaxCylNum, 0, sizeof(mMaxCylNum));
	mServoFormatF = false;
	mProcessingSaF = false;
	mDefaultBytesPerSctLogical = 0;
	mCurrentBytesPerSctLogical = 0;
	mCurrentBytesPerSctPhysical = 0;
	mDCylCellSize = 0;
}

/*--------------------------------------------------------------------------------
 * 開始処理
 *------------------------------------------------------------------------------*/ /* [EN] Initialization process */
void Blocks::open(void)
{
	/* Allocate Buffer＆フォーマット情報取得 - Page0, Page6 */ /* [EN] Allocate buffer and retrieve format information - Page0, Page6 */
	mPage0Tag.allocate(sizeof(FormatInformationPage0));
	pPage0 = reinterpret_cast<FormatInformationPage0*>(mPage0Tag.getMemoryAccessBegin());
	updateFormatInformationPage0();
	mPage6Tag.allocate(sizeof(FormatInformationPage6));
	pPage6 = reinterpret_cast<FormatInformationPage6*>(mPage6Tag.getMemoryAccessBegin());
	updateFormatInformationPage6();
	
	#if !defined Switch_NotSupportedAreaSkip
	/* Allocate Buffer for Page12 */
	mPage12TagCmr.allocate(sizeof(FormatInformationPage12));
	#if defined Switch_Hybrid
	mPage12TagSmr.allocate(sizeof(FormatInformationPage12));
	#endif
	#endif
	
	uint8_t headCount = getHeadCnt();
	debugPrint("Head Count             : %d\n", headCount);
	for(int head = 0; head < headCount; head++)
	{
		debugPrint("Max Cylinder Number(%2d): %08Xh\n", head, mMaxCylNum[head]);
	}
	debugPrint("Standard Symbols/TRK   : %08Xh\n", getStandardSPT());
	debugPrint("Number of Servo Frame  : %d\n", kNumberOfServoFrame);

	/* 初期セクタデータ長を取得 */ /* [EN] Retrieve initial sector data length */
	mCurrentBytesPerSctPhysical = getBytesPerSctPhysical();
	mCurrentBytesPerSctLogical = mDefaultBytesPerSctLogical = getBytesPerSctLogical();
	debugPrint("Bytes/Sector Physical  : %d\n", mCurrentBytesPerSctPhysical);
	debugPrint("Bytes/Sector Logical   : %d\n", mDefaultBytesPerSctLogical);
	debugPrint("Sector Format Info.    : %04Xh\n", swap16(pPage0->mediaFormatInformation));
	debugPrint("F/W SA Zone Number     : %d\n", getFirmwareSaZoneNumber());
	debugPrint("Head Skip Flags        :");
	for(int head = 0; head < headCount; head++)
	{
		debugPrint(" %c", pDrivePrm->isHeadSkipDefault(head) ? 'X' : 'O');
	}
	debugPrint("\n");

	/* データフォーマット設定 */ /* [EN] Data format setting */
	mServoFormatF = false;
	mIsAllZoneDcylTpi = false;
	
	/* DCylのCell Size基準値更新 */ /* [EN] Update DCyl cell size reference value */
	updateDCylCellSize();
	
	#if defined ENABLE_GEOMETRY_MONITER
	disp();
	#endif
}

/*--------------------------------------------------------------------------------
 * フォーマット情報取得 - Page0 (更新)
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve format information - Page0 (update) */
void Blocks::updateFormatInformationPage0(void)
{
	/* フォーマット情報取得 - Page0 */ /* [EN] Retrieve format information - Page 0 */
	uint8_t cdb[kCdbLength] = { 0xE9, 0x72, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(pPage0), sizeof(FormatInformationPage0));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdFormatInfoPage0);
		panic(0);
	}
	
	/* Defect位置登録の為の標準"Symbol数/TRK"の更新 */ /* [EN] Update standard "Symbol count/TRK" for defect location registration */
	mStandardSPT = swap32(pPage0->unformatSymbols);
	/* 最大CYL番号のHead間High/Lowの更新 */ /* [EN] Update of High/Low for maximum CYL number between Heads */
	updateMaxCylHL();
}

/*--------------------------------------------------------------------------------
 * フォーマット情報取得 - Page6 (更新)
 *------------------------------------------------------------------------------*/ /* [EN] Update format information - Page6 */
void Blocks::updateFormatInformationPage6(void)
{
	/* フォーマット情報取得 - Page6 */ /* [EN] Retrieve format information - Page 6 */
	uint8_t cdb[kCdbLength] = { 0xE9, 0x72, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(pPage6), sizeof(FormatInformationPage6));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdFormatInfoPage6);
		panic(0);
	}
}

/*--------------------------------------------------------------------------------
 * Head Skip Tableの論理Head本数
 *------------------------------------------------------------------------------*/ /* [EN] Logical Head count in the Head Skip Table */
uint8_t Blocks::getValidHeadCnt(void)
{
	/* スキップされていない有効Head本数をカウント */ /* [EN] Count the number of valid Heads that are not skipped */
	uint8_t validHeadCnt = 0;
	for(int head = 0; head < getHeadCnt(); head++)
	{
		if(!pDrivePrm->isHeadSkipDefault(head))
		{
			validHeadCnt++;
		}
	}

	return validHeadCnt;
}

/*--------------------------------------------------------------------------------
 * 実装されているHead本数
 *------------------------------------------------------------------------------*/ /* [EN] Implemented number of Heads */
uint8_t Blocks::getMountedHeadCnt(void)
{
	uint32_t mountedHeadBitFlag
		= (pPage0->deviceType[11] << 16) | (pPage0->deviceType[12] << 8) | pPage0->deviceType[13];
	uint8_t counter = 0;
	
	for(int head = 0; head < kTpmHeadCnt; head++)
	{
		if(mountedHeadBitFlag & (1 << head))
		{
			counter++;
		}
	}
	
	return counter;
}

/*--------------------------------------------------------------------------------
 * 装置の容量を総LBA数(スペアも含む)で取得.
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the device capacity as the total number of LBAs including spares. */
void Blocks::getCapacity(double* pTotalBlks, bool isRemoveCtrlWorkArea)
{
	//
	// [装置容量(総LBA数)の取得]
	//  ※Defect, Track Slipは含まれる(考慮されない)。
	//
	// [EN] Device capacity (total LBA count) retrieval includes Defect and Track Slip (not considered).
	if(isRemoveCtrlWorkArea)
	{
		*pTotalBlks = static_cast<double>(swap64(pPage6->noDefectDriveScts));
	}
	else
	{
		*pTotalBlks = static_cast<double>(swap64(pPage6->noDefectDriveSctsWithMC));
	}
}

/*--------------------------------------------------------------------------------
 * ユーザー向け装置容量(総LBA数)を取得.
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve user-facing device capacity (total LBA count). */
uint64_t Blocks::getCapacity4User(void)
{
	//
	// [ユーザー向け装置容量(総LBA数)の取得]
	// 本値は, Read Capacityコマンドで報告するMaxLba No. + 1 と同値.
	//
	// [EN] Retrieve user-facing device capacity (total LBA count). This value is equivalent to MaxLba No.
	// [EN] reported by the Read Capacity command + 1.
	return swap64(pPage6->numberOfLBAs4User);
}

/*--------------------------------------------------------------------------------
 * Zone/Headの最Outer物理CYL番号を取得
 *------------------------------------------------------------------------------*/ /* [EN] Get the outermost physical CYL number for Zone/Head */
int32_t Blocks::getZnSttCyl(uint8_t zone, uint8_t head)
{
	uint8_t segment = zone2Segment(zone, 0);
	if(segment == kSAZoneNumber)
	{
		DeviceSerialNumber serialNumber;
		if(serialNumber.isAllFF())
		{
			/* ※Serial FFなら、SA余剰開放を考慮したSAの最Outer (#16597) */ /* [EN] If Serial is all FF, consider SA remaining release for the most outer SA (#16597) */
			int32_t numberOfCyls = static_cast<int32_t>(
				swap32(pPage6->saSegmentInformation.numberOfCyls[head]) - getDecreasedSaCylNum());
			
			return (0 - numberOfCyls);
		}
		
		/* ※Serial FFでなければ、内部テスト用シリンダの最Outerとする (#16597) */ /* [EN] If not Serial FF, treat as the most Outer cylinder for internal testing (#16597) */
		return kStartSaTestCylNumber - kNumberOfSaTestCyls + 1;
	}
	
	return static_cast<int32_t>(
		swap32(pPage6->userSegmentInformation[segment].startCylinderNumber[head]));
}

/*--------------------------------------------------------------------------------
 * Zone/Headの最Inner物理CYL番号を取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the innermost physical CYL number for Zone/Head */
int32_t Blocks::getZnEndCyl(uint8_t zone, uint8_t head)
{
	uint8_t segment = zone2Segment(zone, kNumberOfSegmentsPerZone - 1);
	if(segment == kSAZoneNumber)
	{
		/* SA Zoneの場合 (#11112) */ /* [EN] If it is SA Zone (#11112) */
		DeviceSerialNumber serialNumber;
		if(serialNumber.isAllFF())
		{
			/* ※Serial FFなら、-1 */ /* [EN] If Serial is FF, return -1 */
			return -1;
		}
		
		/* ※Serial FFでなければ、内部テスト用シリンダの最Innerとする (#16597) */ /* [EN] If not Serial FF, treat as the most Inner cylinder for internal testing (#16597) */
		return kStartSaTestCylNumber;
	}
	
	uint8_t maxSegmentNumber = getMaxZoneNum();
	if(isSegmentMode())
	{
		maxSegmentNumber = kMaxNumberOfUserSegments - 1;
	}
	
	if(segment >= maxSegmentNumber)
	{
		return getMaxCylNum(head);
	}
	
	int32_t startCylNumber = static_cast<int32_t>(
		swap32(pPage6->userSegmentInformation[segment].startCylinderNumber[head]));
	int32_t numberOfCyls = static_cast<int32_t>(
		swap32(pPage6->userSegmentInformation[segment].numberOfCyls[head]));
	
	return startCylNumber + numberOfCyls - 1;
}

/*--------------------------------------------------------------------------------
 * Head/Zone/相対Segmentの最Outer物理CYL番号
 *------------------------------------------------------------------------------*/ /* [EN] Physical outermost CYL number for Head/Zone/relative Segment */
int32_t Blocks::getSegmentStartCyl(uint8_t head, uint8_t zone, uint8_t relSegment)
{
	/*
	 * @note
	 *   Blocks::getStartPhysicalCylinderNumber(segment, head) は使用不可。
	 *   なぜなら、装置が224セグメントモードに切替わっていることが条件だから。
	 *   ここは、32ゾーンモードの場合も参照される関数なので、
	 *   各セグメントの最終シリンダ番号は自前で算出する。
	 *   算出方法は、「MG08 224セグメント対応FW要求仕様」に準拠。
	 */ /* [EN] Blocks::getStartPhysicalCylinderNumber(segment, head) is not usable because the device has switched to 224-segment mode. This function is also referenced in 32-zone mode, so the final cylinder number for each segment must be calculated manually following the "MG08 224-segment corresponding FW requirement specification." */
	if(zone == kSAZoneNumber)
	{
		return kSACylOuterLimit;	/* SAの場合 */ /* [EN] For SA case */
	}
	
	uint16_t numberOfCells = pDrivePrm->getNumberOfCells(zone);
	int32_t cellsPerSegment[kNumberOfSegmentsPerZone] = {0};
	uint32_t r = 0;
	while(numberOfCells > 0)
	{
		cellsPerSegment[r++]++;
		numberOfCells--;
		if(r == kNumberOfSegmentsPerZone)
		{
			r = 0;
		}
	}
	
	int32_t cellSize = pDrivePrm->getCellSize(head, zone);
	int32_t cylinder = getZnSttCyl(zone, head);
	for(r = 0; r < relSegment; r++)
	{
		cylinder += (cellsPerSegment[r] * cellSize);
	}
	
	return cylinder;
}

/*--------------------------------------------------------------------------------
 * Head/Zone/相対Segmentの最Inner物理CYL番号
 *------------------------------------------------------------------------------*/ /* [EN] Physical CYL number of the most inner segment for given Head/Zone/relative Segment */
int32_t Blocks::getSegmentEndCyl(uint8_t head, uint8_t zone, uint8_t relSegment)
{
	/*
	 * @note
	 *   Blocks::getEndPhysicalCylinderNumber(segment, head) は使用不可。
	 *   なぜなら、装置が224セグメントモードに切替わっていることが条件だから。
	 *   ここは、32ゾーンモードの場合も参照される関数なので、
	 *   各セグメントの最終シリンダ番号は自前で算出する。
	 *   算出方法は、「MG08 224セグメント対応FW要求仕様」に準拠。
	 */ /* [EN] Blocks::getEndPhysicalCylinderNumber(segment, head) is not usable because the device has switched to 224-segment mode. This function is also referenced in 32-zone mode, so the final cylinder number for each segment must be calculated manually following the "MG08 224-segment compatible FW requirement specification." */
	if(zone == kSAZoneNumber)
	{
		return -1;	/* SAの場合 */ /* [EN] For SA case */
	}
	
	if(zone == getMaxZoneNum() && relSegment == (kNumberOfSegmentsPerZone - 1))
	{
		return getMaxCylNum(head);	/* 最終Segmentの場合 */ /* [EN] Final segment case */
	}
	
	uint16_t numberOfCells = pDrivePrm->getNumberOfCells(zone);
	int32_t cellsPerSegment[kNumberOfSegmentsPerZone] = {0};
	uint32_t r = 0;
	while(numberOfCells > 0)
	{
		cellsPerSegment[r++]++;
		numberOfCells--;
		if(r == kNumberOfSegmentsPerZone)
		{
			r = 0;
		}
	}
	
	int32_t cellSize = pDrivePrm->getCellSize(head, zone);
	int32_t cylinder = getZnSttCyl(zone, head) - 1;
	for(r = 0; r <= relSegment; r++)
	{
		cylinder += (cellsPerSegment[r] * cellSize);
	}
	
	return cylinder;
}

/*--------------------------------------------------------------------------------
 * Head/Segment(or Zone)のSector数/TRK
 *------------------------------------------------------------------------------*/ /* [EN] Number of Sectors per Track for Head/Segment (or Zone) */
uint16_t Blocks::getSctsPerTrk(uint8_t head, uint32_t segmentOrZone)
{
	if(mServoFormatF)
	{
		return kNumberOfServoFrame;
	}
	else
	{
		if(segmentOrZone == kSAZoneNumber)
		{
			return swap16(pPage6->saSegmentInformation.sectorsPerTrack[head]);
		}
		else
		{
			return swap16(pPage6->userSegmentInformation[segmentOrZone].sectorsPerTrack[head]);
		}
	}
}

/*--------------------------------------------------------------------------------
 * CYL/HeadのSector数/TRK
 *------------------------------------------------------------------------------*/ /* [EN] Sector count per track for CYL/Head */
uint16_t Blocks::getSctsPerTrkCylHd(int32_t cyl, uint8_t head)
{
	if(mServoFormatF)
	{
		return kNumberOfServoFrame;
	}
	else
	{
		uint8_t segment = getSegmentNum(cyl, head);
		if(segment == kSAZoneNumber)
		{
			return swap16(pPage6->saSegmentInformation.sectorsPerTrack[head]);
		}
		else
		{
			return swap16(pPage6->userSegmentInformation[segment].sectorsPerTrack[head]);
		}
	}
}

/*--------------------------------------------------------------------------------
 * SA Cell Size取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve SA Cell Size */
uint16_t Blocks::getSaCellSize(void)
{
	double tpiStw = static_cast<double>(getSTWTPI());
	double tpiNegCyl = static_cast<double>(pDrivePrm->getSlopeOfTpiTransform4SA());							/* SA領域TPI変換係数 */ /* [EN] Conversion coefficient for SA area TPI */
	double tpiCellStd = static_cast<double>(pDrivePrm->getPointerOfReadWriteParameterSA()->getNormalTpi());	/* 最大TPI取得 */ /* [EN] Get maximum TPI */
	
	return static_cast<uint16_t>(roundOwn(tpiStw * pDrivePrm->getNormalCellSize() / tpiCellStd / tpiNegCyl * 16384.0));	/* 2^4 = 16384 */
}

/*--------------------------------------------------------------------------------
 * SA領域開放 減少Cylinder数取得
 *------------------------------------------------------------------------------*/ /* [EN] Get the decreased Cylinder number for SA area release */
uint32_t Blocks::getDecreasedSaCylNum(void)
{
	TrueCircleParameter trueCircle;
	uint8_t releaseCellNum = trueCircle.getReleaseCellNum();
	double decreasedSaCyl = static_cast<double>(calcShiftZeroCyl(releaseCellNum));
	decreasedSaCyl /= static_cast<double>(getSTWTPI());
	decreasedSaCyl *= static_cast<double>(getSaTpi());
	
	return static_cast<uint32_t>(decreasedSaCyl);
}

/*--------------------------------------------------------------------------------
 * STW TPI
 *------------------------------------------------------------------------------*/
uint32_t Blocks::getSTWTPI(void)
{
	return swap32(pPage0->stwTPI);
}

/*--------------------------------------------------------------------------------
 * SA TPI
 *------------------------------------------------------------------------------*/
uint32_t Blocks::getSaTpi(void)
{
	double tpiCellStd = static_cast<double>(pDrivePrm->getPointerOfReadWriteParameterSA()->getNormalTpi());
	double work = static_cast<double>(pDrivePrm->getNormalCellSize()) / tpiCellStd;
	double saTpi = static_cast<double>(getSaCellSize()) / work;
	
	return static_cast<uint32_t>(saTpi);
}

/*--------------------------------------------------------------------------------
 * Cyl.0ずらし量計算
 *------------------------------------------------------------------------------*/ /* [EN] Calculate the Cyl.0 shift amount */
uint16_t Blocks::calcShiftZeroCyl(uint8_t releaseCellNum)
{
	double shiftZeroCyl = static_cast<double>(releaseCellNum);
	shiftZeroCyl *= static_cast<double>(getSTWTPI());
	shiftZeroCyl *= static_cast<double>(pDrivePrm->getNormalCellSize());
	shiftZeroCyl /= static_cast<double>(pDrivePrm->getPointerOfReadWriteParameterSA()->getNormalTpi());
	
	return static_cast<uint16_t>(roundOwn(shiftZeroCyl));
}

/*--------------------------------------------------------------------------------
 * 変換(Offset → nm換算Offset)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Offset → Offset in nm) */
void Blocks::cnvOffset_nm(double* offset, double& dt)
{
	//
	// [機能]
	//  入力の"offset"を1/64Offset単位から、nm換算値に変換し、引数"dt"に格納する。
	//  (引数は"double*")
	//
	// [EN] Convert the input "offset" from 1/64 Offset units to nm equivalent and store it in argument "dt".
	// [EN] (Argument is "double*")
	dt = 25400000;			// 1inch
	dt /= getNormalTPI();	// 1TRKの幅
	// [EN] Width of 1 track
	dt /= 256;				// 1Offsetの幅
	// [EN] Width of 1 Offset
	dt *= (*offset);		// 引数Offsetのnm換算値
	// [EN] Argument Offset's nm conversion value
}

/*--------------------------------------------------------------------------------
 * 変換(nm → Offset換算(dac単位))
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (nm to Offset conversion in dac units) */
void Blocks::cnvNm2Offset(double* nm, double& dac)
{
	/*
	 * [機能]
	 *  入力の"nm"をnm単位から、Offset換算値に変換し、引数"dt"に格納する。
	 *  (引数は"double*")
	 */ /* [EN] Convert input "nm" from nm units to Offset value and store in argument "dac". (Argument is "double&") */
	
	dac = 25400000;			/* 1inch */
	dac /= getNormalTPI();	/* 1TRKの幅 */ /* [EN] Width of 1TRK */
	dac /= 256;				/* 1Offsetのnm距離 */ /* [EN] Distance in nm for 1 Offset */
	dac = *nm / dac;		/* 引数nmのOffset換算値(dac単位) */ /* [EN] Conversion value of Offset in nm units (in dac) */
}

/*--------------------------------------------------------------------------------
 * 変換(CYL/HD/SFI → SCT)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (CYL/HD/SFI to SCT) */
uint16_t Blocks::cnvSFI2Sct(int32_t cyl, uint8_t head, uint32_t SFI)
{
	uint8_t cdb[kCdbLength] = {0};
	cdb[0] = 0xE9;
	cdb[1] = 0xD2;
	*(reinterpret_cast<uint16_t*>(&cdb[2])) = 0x000C;
	*(reinterpret_cast<int32_t*>(&cdb[4])) = cyl;
	*(reinterpret_cast<uint32_t*>(&cdb[8])) = SFI;
	cdb[12] = head;
	pCommand->setCdb(cdb, kCdbLength);
	uint16_t sectorNumber = 0;
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(&sectorNumber), sizeof(uint16_t));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdTpFuncSfi2Sct);
		panic(0);
	}
	
	return sectorNumber;
}

/*--------------------------------------------------------------------------------
 * 物理セクタ長が512基準以外の場合、512基準に変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert block count to 512-byte standard if sector size is not based on 512 bytes */
uint32_t Blocks::cnvBlks_4k(uint32_t blk)
{
	/**
	 * 物理セクタ長が4096以上なら、指定BLK数を1/8換算する.
	 * 計算結果は切上げ.
	 */ /* [EN] If the physical sector length is 4096 or more, convert the specified block count to 1/8. The result is rounded up. */
	if(mCurrentBytesPerSctPhysical >= kMin4KBytesPerSector || isProcessingSa())
	{
		blk = (blk + 7) / 8;	/* ※切上げの為(+7) */ /* [EN] For rounding up (+7) */
	}

	return blk;
}

/*--------------------------------------------------------------------------------
 * Format変更 - TPM開始時状態
 *------------------------------------------------------------------------------*/ /* [EN] Format change - TPM state at startup */
void Blocks::revertOriginalFormat(void)
{
	if(!pSystem->isFirmwareSATA())
	{
		//
		//  本関数はTPM開始前のDWFTおよび、モードパラメータの値に設定し直す。(SAS F/W限定)
		//
		//  <使用箇所>
		//    TPM終了時, LBA(ORT)試験時
		//
		// [EN] This function sets the DWFT and mode parameters before TPM starts (SAS F/W only). Used at TPM end
		// [EN] and during LBA(ORT) testing.
		
		/**
		 * 物理アクセス用変数再計算をする前にModeの設定を済ませておく必要があります
		 */ /* [EN] Before recalculating the physical access variables, Mode settings must be completed. */
		changeModeParameterSectorSize(mDefaultBytesPerSctLogical);
		
		/**
		 * 物理アクセス用変数再計算 (全エリア)
		 */ /* [EN] Recalculate physical access variables for all areas */
		recalculatePhysicalAccessParameter(0xFF, 0xFF);
		
		debugPrint("[Blocks::revertOriginalFormat] %d -> ", mCurrentBytesPerSctLogical);
		mCurrentBytesPerSctLogical = getBytesPerSctLogical();
		mCurrentBytesPerSctPhysical = getBytesPerSctPhysical();
		debugPrint("%d\n", mCurrentBytesPerSctLogical);
	}
}

/*--------------------------------------------------------------------------------
 * Format変更 - SCT Size変更
 *------------------------------------------------------------------------------*/ /* [EN] Change format - Change SCT size */
void Blocks::changeSctSizeFormat(uint16_t logicalSize)
{
	/* (!) SATA F/Wはここに来てはいけません */ /* [EN] SATA firmware should not reach here */
	panic(!pSystem->isFirmwareSATA());
	
	/* 論理セクタ長がカレント値と同じ、又は、512e(4K=1,UncVal=1)なら即リターン */ /* [EN] Logical sector length is the same as current value, or 512e (4K=1, UncVal=1), then return immediately */
	const uint16_t klSctFormatInfo512e = kWORDBitNumber5 | kWORDBitNumber4;
	if(logicalSize == mCurrentBytesPerSctLogical
		|| (swap16(pPage0->mediaFormatInformation) & klSctFormatInfo512e) == klSctFormatInfo512e)
	{
		/**
		 * @note
		 *  DET2/SRT-plusファームは512eは未サポートなので、Mode Selectでセクタ長を
		 *  期待通り変更できない。
		 *  具体的には、"物理セクタ長 = 論理セクタ長 * 8"とはならず、"物理セクタ長 = 論理セクタ長"
		 *  となってしまう。(#13621)
		 */ /* [EN] DET2/SRT-plus firmware does not support 512e, so the sector length cannot be changed as expected in Mode Select. Specifically, "physical sector size = logical sector size * 8" does not hold; instead, "physical sector size = logical sector size". (#13621) */
		debugPrint("[Blocks::changeSctSizeFormat] No change (%d -> %d, %04Xh)\n",
			mCurrentBytesPerSctLogical, logicalSize, swap16(pPage0->mediaFormatInformation));
		return;
	}
	
	/* サポートされているセクタ長かをチェック */ /* [EN] Check if the sector length is supported */
	if(logicalSize != kMinBytesPerSector			/*  512 */
		&& logicalSize != k520BytesPerSector		/*  520 */
		&& logicalSize != k528BytesPerSector		/*  528 */
		&& logicalSize != kMin4KBytesPerSector		/* 4096 */
		&& logicalSize != k4160BytesPerSector		/* 4160 */
		&& logicalSize != k4224BytesPerSector)		/* 4224 */
	{
		logicalSize = mDefaultBytesPerSctLogical;	/* 在り得ないセクタ長は、Defaultに戻す */ /* [EN] Impossible sector length should be reset to Default */
	}
	
	/**
	 * 物理アクセス用変数再計算をする前にModeの設定を済ませておく必要があります
	 */ /* [EN] Before recalculating the physical access variables, the mode settings must be completed. */
	changeModeParameterSectorSize(logicalSize);
	
	/**
	 * 物理アクセス用変数再計算 (全エリア)
	 */ /* [EN] Recalculate physical access variables for all areas */
	recalculatePhysicalAccessParameter(0xFF, 0xFF);
	
	debugPrint("[Blocks::changeSctSizeFormat] %d -> ", mCurrentBytesPerSctLogical);
	mCurrentBytesPerSctLogical = getBytesPerSctLogical();
	mCurrentBytesPerSctPhysical = getBytesPerSctPhysical();
	debugPrint("%d\n", mCurrentBytesPerSctLogical);
}

/*--------------------------------------------------------------------------------
 * 変換(Data Bufferの傷バイトpos,len → Zone 0,標準BPIのSFI傷pos,len)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Data Buffer defect byte pos, len → Zone 0, standard BPI SFI defect pos, len) */
void Blocks::cnvDefectPos(int32_t cyl, uint8_t head, uint16_t sct, uint32_t& pos, uint16_t& length)
{
	//
	//  ★引数の"pos"と"length"はsymbol単位となりました。(2010/10/15)
	//
	//  [Data Buffer]
	//
	//        ┌───xxxxxxxxxxxxxxxxxxxxxxxx──────┐
	//    ──┴─────────────────────┴──
	//               △ pos
	//                ←──   length   ──→
	//
	//                           ↓変換
	//
	//  [実Format]
	//
	//        ┌───xxxxxxxx┐┌─┐┌xxxxxxxxxxxxxxxx────┐
	//    ──┴───────┴┴─┴┴────────────┴──
	//                            SV
	//
	//                           ↓変換
	//
	//  [Defect情報(Zone0,標準BPI)]
	//
	//        ┌───xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx────┐
	//    ──┴───────┴┴─┴┴────────────┴──
	//               △ pos
	//                ←────    length    ────→
	//
	// [EN] Arguments "pos" and "length" are now in symbol units. (2010/10/15)
	
	if(mServoFormatF)
	{
		issuePositionCalculate(cyl, head, sct, false, pos, length);
	}
	else
	{
		/* ※通常Sector Format時は、"cnvDefectPosFull"と同じ出力 */ /* [EN] During normal Sector Format, "cnvDefectPosFull" produces the same output */
		cnvDefectPosFull(cyl, head, sct, pos, length);
	}
}

/*--------------------------------------------------------------------------------
 * 変換(CHS → Zone 0,標準BPIのSFI傷pos,len[対象Sector全体])
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (CHS to Zone 0, standard BPI SFI defect pos, len for entire target sector) */
void Blocks::cnvDefectPosFull(int32_t cyl, uint8_t head, uint16_t sct, uint32_t& pos, uint16_t& length)
{
	//
	//  ★引数の"pos"と"length"はsymbol単位となりました。(2010/10/15)
	//
	//  [Data Buffer]
	//
	//        ┌───xxxxxxxxxxxxxxxxxxxxxxxx──────┐
	//    ──┴─────────────────────┴──
	//        △ pos
	//         ←───────   length   ───────→
	//
	//                           ↓変換
	//
	//  [実Format]
	//
	//        ┌───xxxxxxxx┐┌─┐┌xxxxxxxxxxxxxxxx────┐
	//    ──┴───────┴┴─┴┴────────────┴──
	//                            SV
	//
	//                           ↓変換
	//
	//  [Defect情報(Zone0,標準BPI)]
	//    ※対象SCT全体をDefectとする。(先頭のG1/PLO/SMを含む位置から最後尾のPadまで)
	//
	//         xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
	//    ──┴───────┴┴─┴┴────────────┴──
	//        △ pos
	//         ←────────   length   ─────────→
	//
	// [EN] The arguments "pos" and "length" are now in symbol units. (2010/10/15)

	// Dummy Data入力(SCT内 pos=0,length=1)
	// [EN] Dummy Data input (SCT within pos=0, length=1)
	pos = 0;
	length = 1;
	issuePositionCalculate(cyl, head, sct, true, pos, length);
}

//-----------------------------------------------
// Physical ←→ STW 変換コード
//-----------------------------------------------
// [EN] Physical ↔ STW conversion code
enum {
	kCnvP2STW = 0,
	kCnvSTW2P
};

/*--------------------------------------------------------------------------------
 * 変換(物理CYL → STW基準CYL)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Physical CYL to STW-based CYL) */
int32_t Blocks::cnvCylNumP2STW(int32_t cyl, uint8_t head)
{
	int32_t scyl = issueConvertCylinder(cyl, head, false);
	
	// １対１になるように収束させる
	// [EN] Converge to make it one-to-one
	if(cyl > (getMaxCylNum(head) / 2))
	{
		while(cnvCylNumSTW2P(scyl, head) < cyl)
		{
			scyl++;
		}
		while(cnvCylNumSTW2P(scyl, head) > cyl)
		{
			scyl--;
		}
		// ※Inner側はOuter寄りに仕上げる
		// [EN] Inner side is finished close to Outer
	}
	else
	{
		while(cnvCylNumSTW2P(scyl, head) > cyl)
		{
			scyl--;
		}
		while(cnvCylNumSTW2P(scyl, head) < cyl)
		{
			scyl++;
		}
		// ※Outer側はInner寄りに仕上げる
		// [EN] Outer side is finished close to Inner
	}
	
	return scyl;
}

/*--------------------------------------------------------------------------------
 * 変換(STW基準CYL → 物理CYL)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (STW base CYL to physical CYL) */
int32_t Blocks::cnvCylNumSTW2P(int32_t scyl, uint8_t head)
{
	return issueConvertCylinder(scyl, head, true);
}

/*--------------------------------------------------------------------------------
 * 変換(実Zone FormatのSymbol pos,len → Zone 0,標準BPIのSymbol pos,len)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Real Zone Format Symbol position and length → Zone 0, Standard BPI Symbol position and length) */
void Blocks::cnvStandardBPI(int32_t cyl, uint8_t head, uint32_t& SFI, uint16_t& len)
{
	//
	// [略語解説]
	//    BPI   : Bit Per Inch (円周方向に対する面密度を表す単語)
	//    SFI   : Symbol From Index
	//    SPT   : Symbol Per Track
	//    Symbol: 10BitのNRZ(8Symbol = 10Byte)
	//
	// [EN] Abbreviation explanation BPI: Bit Per Inch (unit representing linear density) SFI: Symbol From Index
	// [EN] SPT: Symbol Per Track Symbol: 10-bit NRZ (8 symbols = 10 bytes)
	uint64_t currentSPT = getSymbolsPerTrack(cyl, head);
	uint64_t work;
	QWordByteU temp;

//	debugPrint("SPT Ratio: cur : std = %08X : %08X\n", (uint32_t)currentSPT, (uint32_t)mStandardSPT);
//	debugPrint("Orginal (SFI:%08X, Len:%04X)\n", SFI, len);

	// SFI変換(四捨五入→切り上げ ： TP Functionの「標準SFI→SCT変換」との誤差を解消 ： #15489)
	// [EN] SFI conversion (rounding up: eliminate error in "standard SFI to SCT conversion" of TP Function:
	// [EN] #15489)
	work = static_cast<uint64_t>(SFI);
	temp.qw = ((work * mStandardSPT) + currentSPT - 1) / currentSPT;
	SFI = temp.lw[0];

	// Length変換(四捨五入→切り上げ ： TP Functionの「標準SFI→SCT変換」との誤差を解消 ： #15489)
	// [EN] Length conversion (rounding up: eliminate error from "standard SFI to SCT conversion" in TP
	// [EN] function: #15489)
	work = static_cast<uint64_t>(len);
	temp.qw = ((work * mStandardSPT) + currentSPT - 1) / currentSPT;
	len = temp.w[0];
	if(len == 0)
	{
		len = 1;
	}

//	debugPrint("-> Standard (SFI:%08X, Len:%04X)\n", SFI, len);
}

/*--------------------------------------------------------------------------------
 * 変換(Zone 0,標準BPIのSymbol pos,len → 実Zone FormatのSymbol pos,len)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Zone 0, standard BPI symbol position and length → actual Zone Format symbol position and length) */
void Blocks::cnvCurrentBPI(int32_t cyl, uint8_t head, uint32_t& SFI, uint16_t& len)
{
	uint64_t currentSPT = getSymbolsPerTrack(cyl, head);
	uint64_t work;
	QWordByteU temp;

//	debugPrint("SPT Ratio: cur : std = %08X : %08X\n", (uint32_t)currentSPT, (uint32_t)mStandardSPT);
//	debugPrint("Standard (SFI:%08X, Len:%04X)\n", SFI, len);

	// SFI変換(四捨五入 #78266)
	// [EN] SFI conversion (rounding #78266)
	work = static_cast<uint64_t>(SFI);
	temp.qw = ((work * currentSPT) + (mStandardSPT / 2)) / mStandardSPT;
	SFI = temp.lw[0];

	// Length変換(四捨五入 #78266)
	// [EN] Length conversion (rounding #78266)
	work = static_cast<uint64_t>(len);
	temp.qw = ((work * currentSPT) + (mStandardSPT / 2)) / mStandardSPT;
	len = temp.w[0];
	if(len == 0)
	{
		len = 1;
	}

//	debugPrint("-> Current (SFI:%08X, Len:%04X)\n", SFI, len);
}

/*--------------------------------------------------------------------------------
 * 変換(Zone 0,標準BPIのSFI → Servo Number
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Zone 0, standard BPI SFI to Servo Number */
uint16_t Blocks::cnvStanderdSfi2ServoNumber(uint32_t standardSfi)
{
	return ((standardSfi * kNumberOfServoFrame) / mStandardSPT);
}

/*--------------------------------------------------------------------------------
 * 装置Defect Mapから装置P-Listに変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert device Defect Map to device P-List */
bool Blocks::makePList(Tag* pDefMapTag, Tag* pPListTag)
{
	DeviceSerialNumber serialNumber;
	if(serialNumber.isAllFF())
	{
		debugPrint("[Blocks::makePList] Serial ALL FF!\n");
		panic(0);	/* ※Debug不足 */ /* [EN] Insufficient debugging */
	}
	
	/* 装置Defect MapをWrite SA */ /* [EN] Write SA for device Defect Map */
	if(!pCommand->writeSA(kSaCdDevDM, pDefMapTag->getMemoryAccessBegin(), pDefMapTag->getMemoryAccessSize()))
	{
		pSenseData->makeFromDiskSense();
		debugPrint("[Blocks::makePList] Device defect map SA save failure! (%08X)\n",
			pSenseData->getSenseCode());
		return false;
	}
	
	/* SA Code=0014h(Media Accessレス)でRead SAコマンド発行 */ /* [EN] Issue Read SA command with SA Code=0014h (Media Access error) */
	if(!pCommand->readSA(0x0014, pPListTag->getMemoryAccessBegin(), pPListTag->getMemoryAccessSize()))
	{
		pSenseData->makeFromDiskSense();
		debugPrint("[Blocks::makePList] Convert Defect map to P-List failure! (%08X)\n",
			pSenseData->getSenseCode());
		return false;
	}
	
	return true;
}

/*--------------------------------------------------------------------------------
 * Defect管理Listの作成とSAセーブ
 *------------------------------------------------------------------------------*/ /* [EN] Creation of Defect management list and SA save */
bool Blocks::updateDML(Tag*)
{
	return true;
}

/*--------------------------------------------------------------------------------
 * 最大CYLのSTWモード変更
 *------------------------------------------------------------------------------*/ /* [EN] Change STW mode for maximum CYL */
void Blocks::setSTWCylMode(bool onoff)
{
	mSTWCylModeF = onoff;
	updateMaxCylHL();
}

/*--------------------------------------------------------------------------------
 * Geometry TBL更新
 *------------------------------------------------------------------------------*/ /* [EN] Update Geometry Table */
void Blocks::resetGeometryTbl(void)
{
	/**
	 * BPIまたはTPI変更後に行う、Blocks変数の初期化
	 * (Set Device Info.と同じ処理)
	 */ /* [EN] Initialization of Blocks variables after changing BPI or TPI (same process as Set Device Info.) */
	
	/**
	 * 物理アクセス用変数再計算 (全エリア)
	 */ /* [EN] Recalculate physical access variables for all areas */
	recalculatePhysicalAccessParameter(0xFF, 0xFF);
}

/*--------------------------------------------------------------------------------
 * Geometry TBL更新(BPIのみ変更用簡易版)
 *------------------------------------------------------------------------------*/ /* [EN] Update Geometry Table (Simplified version for BPI only) */
void Blocks::resetGeometryTbl4TuneBpiFast(uint8_t head, uint8_t zone)
{
	/**
	 * 物理アクセス用変数再計算 (指定Head, Zone限定)
	 */ /* [EN] Recalculate physical access variables for specified Head and Zone only */
	recalculatePhysicalAccessParameter(head, zone);
}

/*--------------------------------------------------------------------------------
 * Servo Defect TBLを装置側に転送
 *------------------------------------------------------------------------------*/ /* [EN] Transfer Servo Defect Table to device side */
void Blocks::xfrTrackSlipTable(Tag* pBufTag, uint32_t dataLen)
{
	/* Header ID */
	pBufTag->write32BigEndian(b2lw('S', 'V', 'D', '2'), 0);
	#if defined Switch_Hybrid
	if(pDisk->isSmr())
	{
		pBufTag->write8('s', 3);	/* '2'→'s' */
	}
	#endif
	
	/* 有効データ長 + エンドマーク分(+1) */ /* [EN] Effective data length + end mark (+1) */
	pBufTag->write32BigEndian(dataLen + 4, 0x0C);
	
	/* エンドマーク付加 */ /* [EN] Appending end mark */
	pBufTag->write32BigEndian(0x7FFFFFFF, kSAHeaderLen + dataLen);
	
	/**
	 * Buffer Data転送
	 *   ※Write SAコマンドのMemory=1指定で代替
	 */ /* [EN] Buffer data transfer Write SA command with Memory=1 specified as an alternative */
	if(!pCommand->writeSA(
		#if defined Switch_Hybrid
		(pDisk->isSmr() ? kSaCdDevTrkSlipSmr : kSaCdDevTrkSlip),
		#else
		kSaCdDevTrkSlip,
		#endif
		pBufTag->getMemoryAccessBegin(),
		pBufTag->getMemoryAccessSize(),
		true))
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrXferDeviceTrkSlip);
		panic(0);
	}
}

/*--------------------------------------------------------------------------------
 * 変更予定の装置Track Slip TBLを事前チェック
 *------------------------------------------------------------------------------*/ /* [EN] Pre-check the planned device Track Slip TBL */
bool Blocks::precheckDeviceTrackSlipTbl(Tag* pTrackSlipTag, uint32_t dataLen, uint32_t& skipHeadFlag)
{
	debugPrint("[Blocks::precheckDeviceTrackSlipTbl]\n");
	
	/* SkipすべきHead番号を示す出力データフラグの初期化 */ /* [EN] Initialization of the output data flag indicating the Head number to be skipped */
	skipHeadFlag = 0;
	
	/* Header ID、有効データ長、エンドマーク付加 */ /* [EN] Header ID, valid data length, end mark appended */
	pTrackSlipTag->write32BigEndian(b2lw('S', 'V', 'D', '2'), 0);
	#if defined Switch_Hybrid
	if(pDisk->isSmr())
	{
		pTrackSlipTag->write8('s', 3);	/* '2'→'s' */
	}
	#endif
	pTrackSlipTag->write32BigEndian(dataLen + 4, 0x0C);
	pTrackSlipTag->write32BigEndian(0x7FFFFFFF, kSAHeaderLen + dataLen);
	
	/*
	 * Track Slip制御テーブルに収まるかチェック
	 */ /* [EN] Check if it fits in the Track Slip control table */
	struct STrackSlipEntryOutput		/**< TrackSlip制御テーブル登録情報 */ /* [EN] TrackSlip control table registration information */
	{
		uint32_t totalNumberOfTracks;	/**< 全Headの合計Track本数 */ /* [EN] Total number of tracks for all heads */
		uint32_t totalNumberOfEntry;	/**< 全Headの合計Entry登録数 */ /* [EN] Total number of Entry registrations for all Heads */
		#if defined Switch_TrackSlipEntryOutput10D
		uint32_t numberOfTracks[20];	/**< 各HeadのTrack本数 (4byte*20Head) */ /* [EN] Number of Tracks per Head (4 bytes * 20 Heads) */
		uint32_t numberOfEntry[20];		/**< 各HeadのEntry登録数 (4byte*20Head) */ /* [EN] Each Head's Entry registration count (4byte*20Head) */
		#else
		uint32_t numberOfTracks[24];	/**< 各HeadのTrack本数 (4byte*24Head) */ /* [EN] Number of Tracks per Head (4 bytes * 24 Heads) */
		uint32_t numberOfEntry[24];		/**< 各HeadのEntry登録数 (4byte*24Head) */ /* [EN] Number of Entry registrations for each Head (4 bytes * 24 Heads) */
		#endif
	} trackSlipEntryOutput;
	
	uint8_t cdb[kCdbLength] = {0};
	cdb[0] = 0xE9;
	cdb[1] = 0xD2;
	/* トラックスリップ制御テーブル登録事前情報取得 (Function Code = 0x000F) */ /* [EN] Retrieve pre-information for track slip control table registration (Function Code = 0x000F) */
	*(reinterpret_cast<uint16_t*>(&cdb[2])) = 0x000F;
	cdb[4] = 0;	/* Memory指定 */ /* [EN] Memory specification */
	*(reinterpret_cast<uint32_t*>(&cdb[8])) = reinterpret_cast<uint32_t>(pTrackSlipTag->getMemoryAccessBegin());
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(&trackSlipEntryOutput), sizeof(trackSlipEntryOutput));
	pCommand->run();	/* コマンド実行 */ /* [EN] Execute command */
	pSenseData->makeFromDiskSense();
	ErrorCode errcode = static_cast<ErrorCode>(pSenseData->getSenseCode());
	uint32_t numberOfEntry = trackSlipEntryOutput.totalNumberOfEntry;
	
	/* Track Slip制御テーブルの最後のデータはEndMarkのため、最大数-1まで許容 */ /* [EN] The last data in the Track Slip control table is an EndMark, so up to maximum number minus one is allowed. */
	if(errcode == kSCodeNoSense && numberOfEntry < kMaxNumberOfTrackSlipsCtrlTable)
	{
		debugPrint(" -> OK\n");
		return true;
	}
	
	/* “03-19-BB-05”以外の不明コードなら、デバッグ不足 */ /* [EN] If the code is not "03-19-BB-05" and unknown, then there is insufficient debugging */
	if(errcode != kSCodeNoSense && errcode != kSCodeServoDefectCtrlTableEntryOver)
	{
		/***** Flash Log *****/
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdTpFuncTrkSlipCtrl);
		debugPrint(" F/W Logical Error ! (%08X)\n", static_cast<uint32_t>(errcode));
		panic(0);
	}
	
	/**
	 * “03-19-BB-05”なら、SkipすべきHeadを「Defect Scanning仕様書」3-5章に基づきサーチ
	 */ /* [EN] If "03-19-BB-05", search for Heads to Skip based on Section 3-5 of the Defect Scanning Specification Document. */
	
	/* バブルソート (Slipped Track本数の多い順にHead番号を並べ替え) */ /* [EN] Bubble sort (Sort Head numbers in descending order of Slipped Track count) */
	uint8_t sortedHeadNumber[kTpmHeadCnt];
	uint8_t headCount = getHeadCnt();
	for(int head = 0; head < headCount; head++)
	{
		sortedHeadNumber[head] = head;
	}
	for(int i = 0; i < headCount - 1; i++)
	{
		for(int j = headCount - 1; j > i; j--)
		{
			if(trackSlipEntryOutput.numberOfTracks[sortedHeadNumber[j - 1]]
				< trackSlipEntryOutput.numberOfTracks[sortedHeadNumber[j]])
			{
				uint8_t tempHeadNumber = sortedHeadNumber[j - 1];
				sortedHeadNumber[j - 1] = sortedHeadNumber[j];
				sortedHeadNumber[j] = tempHeadNumber;
			}
		}
	}
	
	debugPrint(" totalNumberOfTracks=%d\n", trackSlipEntryOutput.totalNumberOfTracks);
	debugPrint(" totalNumberOfEntry=%d (> %d)\n", numberOfEntry, kMaxNumberOfTrackSlipsCtrlTable);
															/* kMaxNumberOfTrackSlipsCtrlTable = 56320 */
	for(int i = 0; i < headCount; i++)
	{
		uint8_t head = sortedHeadNumber[i];
		debugPrint(" head %2d: numberOfTracks=%d, numberOfEntry=%d\n",
			head, trackSlipEntryOutput.numberOfTracks[head], trackSlipEntryOutput.numberOfEntry[head]);
	}
	
	/* Head Skip候補を探す */ /* [EN] Search for Head Skip candidates */
	uint32_t selectedIndex[kTpmHeadCnt];
	for(uint32_t selectHeadCount = 1; selectHeadCount < headCount; selectHeadCount++)
	{
		uint32_t loopCount = getCombiCount(headCount, selectHeadCount);
		for(uint32_t step = 0; step < loopCount; step++)
		{
			skipHeadFlag = 0;
			getCombiPatternPermutation(headCount, selectHeadCount, step, selectedIndex);
			
			uint32_t reduction = 0;
			for(uint32_t cnt = 0; cnt < selectHeadCount; cnt++)
			{
				uint8_t head = sortedHeadNumber[selectedIndex[cnt]];
				reduction += trackSlipEntryOutput.numberOfEntry[head];
				skipHeadFlag |= (1 << head);
			}
			
			if((numberOfEntry - reduction) <= kMaxNumberOfTrackSlipsCtrlTable)
			{
				debugPrint(" -> NG (head flag: %08X)\n", skipHeadFlag);
				return false;
			}
		}
	}
	
	/* ※普通ここまで来ない筈。→ 全Head SkipでTPMストップへ */ /* [EN] Normal execution should not reach here. Proceeding to TPM stop with full Head Skip. */
	skipHeadFlag = 0xFFFFFFFF;
	debugPrint(" -> Contradiction NG\n");
	return false;
}

/*--------------------------------------------------------------------------------
 * Head Skip Tableの物理Head本数
 *------------------------------------------------------------------------------*/ /* [EN] Physical Head count in Head Skip Table */
uint8_t Blocks::getHeadCnt(void)
{
	return pPage0->numberOfPhysicalHeads;
}

/*--------------------------------------------------------------------------------
 * ユーザーゾーン数の取得
 *------------------------------------------------------------------------------*/ /* [EN] Get the number of user zones */
uint8_t Blocks::getZoneCnt(void)
{
	return kNumberOfMaxZones;
}

/*--------------------------------------------------------------------------------
 * 各Headの最大CYL番号(カレントのTPM試験範囲)
 *------------------------------------------------------------------------------*/ /* [EN] Maximum CYL number for each Head (current TPM test range) */
int32_t Blocks::getMaxCylNum(uint8_t head)	///< 各Headの最大CYL番号
// [EN] Maximum CYL number for each Head
{
	return mMaxCylNum[head];
}

/*--------------------------------------------------------------------------------
 * 全Headの最大CYL番号中の最大値
 *------------------------------------------------------------------------------*/ /* [EN] Maximum CYL number among all Heads */
int32_t Blocks::getMaxCylNumH(void)
{
	return mMaxCylNumH;
}

/*--------------------------------------------------------------------------------
 * 全Headの最大CYL番号中の最小値
 *------------------------------------------------------------------------------*/ /* [EN] Minimum of maximum CYL numbers across all heads */
int32_t Blocks::getMaxCylNumL(void)
{
	return mMaxCylNumL;
}

/*--------------------------------------------------------------------------------
 * 各Headの最大CYL番号(User Area)
 *------------------------------------------------------------------------------*/ /* [EN] Maximum CYL number for each Head (User Area) */
int32_t Blocks::getMaxCylNumUser(uint8_t head)
{
	return static_cast<int32_t>(swap32(pPage0->numberOfTracksLBA[head])) - 1;
}

/*--------------------------------------------------------------------------------
 * 各Headの限界CYL番号(最大物理CYL) ※Post Codeは本当の限界まで余分に書く
 *------------------------------------------------------------------------------*/ /* [EN] Limit CYL number (maximum physical CYL) for each Head. Note that Post Code writes extra up to the actual limit. */
int32_t Blocks::getLimitCylNum(uint8_t head)
{
	return static_cast<int32_t>(swap32(pPage0->numberOfTracksAll[head])) - 1;
}

/*--------------------------------------------------------------------------------
 * 各HeadのDummy Write開始シリンダ
 *------------------------------------------------------------------------------*/ /* [EN] Start cylinder for Dummy Write for each Head */
int32_t Blocks::getStartDmyWtCyl(uint8_t head)
{
	return static_cast<int32_t>(swap32(pPage0->numberOfTracksUser[head])) + kPadCylindersAlt2DummyWT;
}

/*--------------------------------------------------------------------------------
 * 最大Zone番号
 *------------------------------------------------------------------------------*/ /* [EN] Maximum Zone number */
uint8_t Blocks::getMaxZoneNum(void)
{
	return kNumberOfMaxZones - 1;
}

/*--------------------------------------------------------------------------------
 * 最大物理Head番号
 *------------------------------------------------------------------------------*/ /* [EN] Maximum physical head number */
uint8_t Blocks::getMaxHeadNum(void)
{
	return getHeadCnt() - 1;
}

/*--------------------------------------------------------------------------------
 * 物理セクタのバイト数を装置から取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the byte count of a physical sector from the device */
uint16_t Blocks::getBytesPerSctPhysical(void)
{
	if(pSystem->isFirmwareSATA())
	{
		uint8_t cdb[kCdbLength] = {0};
		uint8_t xfrData[klSizeOfDiskSectorFormat] = {0};
		
		/* Disk Sector Formatの"DATA BYTES PER PHYSICAL SECTOR"(Offset12-15)を読む */ /* [EN] Read "DATA BYTES PER PHYSICAL SECTOR" (Offset 12-15) of Disk Sector Format */
		cdb[0] = 0xFA;
		cdb[1] = 0x07;
		pCommand->setCdb(cdb, kCdbLength);
		pCommand->setXfrData(xfrData, sizeof(xfrData));
		if(!pCommand->run())
		{
			pCommand->forceDisplay();
			pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdDiskSectorFormat);
			panic(0);
		}
		
		return getBigEndianLWORD(&xfrData[12]);	/* ※上位2バイトは捨てる */ /* [EN] Discard the upper 2 bytes */
	}
	else
	{
		uint8_t cdb[kCdbLength10] = {0};
		uint8_t xfrData[klSizeOfModeParameterPage03] = {0};
		
		/* Mode Page03の"DATA BYTES PER PHYSICAL SECTOR"(Offset20-21)を読み込み */ /* [EN] Read "DATA BYTES PER PHYSICAL SECTOR" (Offset 20-21) from Mode Page03 */
		cdb[0] = 0x5A;
		cdb[1] = 0x18;	/* LLBAA(Long LBA)=1, DBD=1 */
		cdb[2] = 0x03;	/* Page03 */
		cdb[8] = klSizeOfModeParameterPage03;
		pCommand->setCdb(cdb, kCdbLength10);
		pCommand->setXfrData(xfrData, klSizeOfModeParameterPage03);
		if(!pCommand->run())
		{
			pCommand->forceDisplay();
			pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdModeSensePage03);
			panic(0);
		}
		
		return getBigEndianWORD(&xfrData[20]);	/* ※ここは2バイト */ /* [EN] This is 2 bytes */
	}
}

/*--------------------------------------------------------------------------------
 * 論理セクタのバイト数を装置から取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the number of bytes per logical sector from the device */
uint16_t Blocks::getBytesPerSctLogical(void)
{
	if(pSystem->isFirmwareSATA())
	{
		uint8_t cdb[kCdbLength] = {0};
		uint8_t xfrData[klSizeOfDiskSectorFormat] = {0};
		
		/* Disk Sector Formatの"LOGICAL BLOCK LENGTH"(Offset8-11)を読む */ /* [EN] Read "LOGICAL BLOCK LENGTH" (Offset 8-11) of Disk Sector Format */
		cdb[0] = 0xFA;
		cdb[1] = 0x07;
		pCommand->setCdb(cdb, kCdbLength);
		pCommand->setXfrData(xfrData, sizeof(xfrData));
		if(!pCommand->run())
		{
			pCommand->forceDisplay();
			pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdDiskSectorFormat2);
			panic(0);
		}
		
		return getBigEndianLWORD(&xfrData[8]);	/* ※上位2バイトは捨てる */ /* [EN] Discard the upper 2 bytes */
	}
	else
	{
		uint8_t cdb[kCdbLength10] = {0};
		uint8_t xfrData[klSizeOfBlockDescriptor] = {0};
		
		/* Block Descriptorの"LOGICAL BLOCK LENGTH"(Offset20-23)を読む */ /* [EN] Read "LOGICAL BLOCK LENGTH" (Offset 20-23) from Block Descriptor */
		cdb[0] = 0x5A;
		cdb[1] = 0x10;	/* LLBAA(Long LBA)=1, DBD=0 */
		cdb[8] = klSizeOfBlockDescriptor;
		pCommand->setCdb(cdb, kCdbLength10);
		pCommand->setXfrData(xfrData, klSizeOfBlockDescriptor);
		if(!pCommand->run())
		{
			pCommand->forceDisplay();
			pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdModeSenseBlock);
			panic(0);
		}
		
		return getBigEndianLWORD(&xfrData[20]);	/* ※上位2バイトは捨てる */ /* [EN] Discard the upper 2 bytes */
	}
}

/*--------------------------------------------------------------------------------
 * 標準TPI
 *------------------------------------------------------------------------------*/ /* [EN] Standard TPI */
uint32_t Blocks::getNormalTPI(void)
{
	return swap32(pPage0->standardTPI);
}

/*--------------------------------------------------------------------------------
 * 変換(Symbol → Byte)
 *------------------------------------------------------------------------------*/ /* [EN] Conversion (Symbol → Byte) */
uint32_t Blocks::cnvSymbol2Byte(uint32_t symbolValue)
{
	/* symbol → byte変換コマンド */ /* [EN] Symbol to byte conversion command */
	uint8_t cdb[kCdbLength] = {0};
	cdb[0] = 0xE9;
	cdb[1] = 0x71;
	cdb[6] = kBYTEBitNumber0;
	cdb[7] = static_cast<uint8_t>((symbolValue >> 24) & kMask_7_0);
	cdb[8] = static_cast<uint8_t>((symbolValue >> 16) & kMask_7_0);
	cdb[9] = static_cast<uint8_t>((symbolValue >> 8) & kMask_7_0);
	cdb[10] = static_cast<uint8_t>(symbolValue & kMask_7_0);
	
	uint32_t byteValueBigEndian;
	
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(&byteValueBigEndian), sizeof(uint32_t));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdSfi2Bfi);
		panic(0);
	}
	
	return swap32(byteValueBigEndian);
}

/*--------------------------------------------------------------------------------
 * 本クラスの機能をServo Formatモード(SectorをServo単位化)に変更
 *------------------------------------------------------------------------------*/ /* [EN] Change the functionality of this class to Servo Format mode (sector as servo unit) */
void Blocks::setServoFormat(void)
{
	mServoFormatF = true;
}

/*--------------------------------------------------------------------------------
 * 本クラスの機能をServo Formatモード(SectorをServo単位化)から元に戻す
 *------------------------------------------------------------------------------*/ /* [EN] Reset the functionality of this class from Servo Format mode (Sector unitized as Servo) to its original state */
void Blocks::resetServoFormat(void)
{
	mServoFormatF = false;
}

/*--------------------------------------------------------------------------------
 * 本クラスの機能がServo Formatモード(SectorをServo単位化)か否かを判定
 *------------------------------------------------------------------------------*/ /* [EN] Determines whether the functionality of this class is in Servo Format mode (sector unitization by servo) or not */
bool Blocks::isServoFormat(void)
{
	return mServoFormatF;
}

/*--------------------------------------------------------------------------------
 * Segment番号変換(cyl/head → Segment)
 *------------------------------------------------------------------------------*/ /* [EN] Convert segment number (cyl/head to Segment) */
uint8_t Blocks::getSegmentNum(int32_t cyl, uint8_t head)
{
	if(cyl < 0)
	{
		if(cyl < getZnSttCyl(kSAZoneNumber, head))
		{
			return kInvalidZoneNumber;
		}
		
		return kSAZoneNumber;
	}
	
	uint32_t numberOfUserSegments = kMaxNumberOfUserSegments;
	if(!isSegmentMode())
	{
		/* ※224Segmentでない場合、コントローラではSegment数はZone数扱い */ /* [EN] If not in 224Segment mode, the controller treats the number of segments as the number of zones. */
		numberOfUserSegments = pPage0->numberOfUserZones;
	}
	
	/* 2分探索 (#16701) */ /* [EN] Binary search (#16701) */
	uint8_t left = 0;
	uint8_t right = numberOfUserSegments - 1;
	while(left < right)
	{
		uint8_t mid = (left + right) / 2;
		int32_t startCylinderNumber = static_cast<int32_t>(
			swap32(pPage6->userSegmentInformation[mid].startCylinderNumber[head]));
		if(cyl >= startCylinderNumber)
		{
			int32_t numberOfCyls = static_cast<int32_t>(
				swap32(pPage6->userSegmentInformation[mid].numberOfCyls[head]));
			if(cyl < (startCylinderNumber + numberOfCyls))
			{
				return mid;
			}
			
			left = mid + 1;
		}
		else
		{
			right = mid;
		}
	}
	
	return right;
}

/*--------------------------------------------------------------------------------
 * Zone番号変換(cyl/head → Zone)
 *------------------------------------------------------------------------------*/ /* [EN] Zone number conversion (cyl/head → Zone) */
uint8_t Blocks::getZoneNum(int32_t cyl, uint8_t head)
{
	return segment2Zone(getSegmentNum(cyl, head));
}

/*--------------------------------------------------------------------------------
 * Cell番号変換(cyl/head → Cell)
 *------------------------------------------------------------------------------*/ /* [EN] Convert cell number (cyl/head to Cell) */
uint32_t Blocks::getCellNum(int32_t cyl, uint8_t head)
{
	if(cyl < 0)
	{
		/* ※SAはCell番号へ変換不可のため 0 を返すこととする. 使用側で注意すること. */ /* [EN] Return 0 since SA cannot be converted to a Cell number. Note this in the usage side. */
		return 0;
	}
	
	uint8_t segment = getSegmentNum(cyl, head);
	
	uint32_t cellNum = (cyl - swap32(pPage6->userSegmentInformation[segment].startCylinderNumber[head]))
					/ swap32(pPage6->userSegmentInformation[segment].numberOfTrackInCell[head])
					+ swap32(pPage6->userSegmentInformation[segment].startCellNumber);
	
	return cellNum;
}

/*--------------------------------------------------------------------------------
 * Format情報Page6「SA Segment Information」のSegment Numberを取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the Segment Number from Format information Page 6 "SA Segment Information" */
uint8_t Blocks::getFirmwareSaZoneNumber(void)
{
	uint8_t saSegNum = static_cast<uint8_t>(pPage6->saSegmentInformation.segmentNumber);
	
	if(saSegNum == 0)
	{
		saSegNum = kSASegmentNumber;
	}
	
	return saSegNum;
}

/*--------------------------------------------------------------------------------
 * Zone 0,標準BPIのSymbol数/Track
 *------------------------------------------------------------------------------*/ /* [EN] Zone 0 standard BPI symbol count per track */
uint32_t Blocks::getStandardSPT(void)
{
	return mStandardSPT;
}

/*--------------------------------------------------------------------------------
 * Max Cylinder Number(H/L) の更新
 *------------------------------------------------------------------------------*/ /* [EN] Update Max Cylinder Number (H/L) */
void Blocks::updateMaxCylHL(void)
{
	mMaxCylNumH = 0;
	mMaxCylNumL = 0x7FFFFFFF;
	int32_t cyl = 0;
	
	for(int head = 0; head < getHeadCnt(); head++)
	{
		if(mSTWCylModeF)					// STW Cylinderモード チェック
		// [EN] Check STW Cylinder mode
		{
			TrueCircleParameter trueCircle;
			cyl = cnvCylNumSTW2P(trueCircle.getCalMaxStwCylinder(), head);
		}
		else
		{
			cyl = static_cast<int32_t>(swap32(pPage0->numberOfTracksUser[head])) - 1;
		}
		
		mMaxCylNum[head] = cyl;				// 各Headの最大CYL番号を設定
		// [EN] Set the maximum CYL number for each Head
		
		if(cyl > mMaxCylNumH)
		{
			mMaxCylNumH = cyl;
		}
		
		if(cyl < mMaxCylNumL)
		{
			mMaxCylNumL = cyl;
		}
	}
}

/*--------------------------------------------------------------------------------
 * Track当たりのSymbol数の取得
 *------------------------------------------------------------------------------*/ /* [EN] Get the number of symbols per track */
uint32_t Blocks::getSymbolsPerTrack(int32_t cylinder, uint8_t head)
{
	uint32_t symbolsPerTrack;
	uint8_t segment = getSegmentNum(cylinder, head);
	if(segment == kSAZoneNumber)
	{
		symbolsPerTrack = swap32(pPage6->saSegmentInformation.symbolsPerTrk[head]);
	}
	else
	{
		symbolsPerTrack = swap32(pPage6->userSegmentInformation[segment].symbolsPerTrk[head]);
	}
	
	return symbolsPerTrack;
}

/*--------------------------------------------------------------------------------
 * Zone番号からSegment番号に変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert Zone number to Segment number */
uint8_t Blocks::zone2Segment(uint8_t zone, uint8_t relativeSegment)
{
	uint8_t segment = zone;
	
	/* ※SAだけはSegment番号への変換不可。既にSegment化(SAなら240)されている事前提！ */ /* [EN] Only SA cannot be converted to a segment number. It is assumed that it is already segmented (if SA, then 240)! */
	if(segment != kSAZoneNumber)
	{
		if(isSegmentMode())	/* 224Segmentモード？ */ /* [EN] 224 Segment mode? */
		{
			segment *= kNumberOfSegmentsPerZone;	/* 7倍 */ /* [EN] Seven times */
			segment += relativeSegment;
			if(segment > (kMaxNumberOfUserSegments - 1))
			{
				segment = kMaxNumberOfUserSegments - 1;	/* 念のため'223'でクリップ */ /* [EN] Clip at '223' just in case */
			}
		}
	}
	
	return segment;
}

/*--------------------------------------------------------------------------------
 * Segment番号からZone番号に変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert Segment number to Zone number */
uint8_t Blocks::segment2Zone(uint8_t segment)
{
	uint8_t zone = segment;
	
	/* ※SAだけはZone番号への変換不可。既にSegment化(SAなら240)されている事前提！ */ /* [EN] Only SA cannot be converted to a Zone number. It is assumed that it is already segmented (240 for SA)! */
	if(zone != kSAZoneNumber)
	{
		if(isSegmentMode())	/* 224Segmentモード？ */ /* [EN] 224 Segment mode? */
		{
			zone /= kNumberOfSegmentsPerZone;	/* 7で割って小数は切捨て */ /* [EN] Divide by seven and discard the fractional part */
			if(zone > (kNumberOfMaxZones - 1))
			{
				zone = kNumberOfMaxZones - 1;	/* 念のため'31'でクリップ */ /* [EN] Clip to '31' for safety */
			}
		}
	}
	
	return zone;
}

/*--------------------------------------------------------------------------------
 * 224Segment Mode?
 *------------------------------------------------------------------------------*/
bool Blocks::isSegmentMode(void)
{
	if(pPage6->numberOfSegmentPerZone == kNumberOfSegmentsPerZone)
	{
		return true;
	}
	
	return false;
}

/*--------------------------------------------------------------------------------
 * モードパラメータのセクタサイズ変更
 *------------------------------------------------------------------------------*/ /* [EN] Change sector size in mode parameters */
void Blocks::changeModeParameterSectorSize(uint16_t logicalSize)
{
	/**
	 * 論理セクタ長の変更 (Block Descriptorの"LOGICAL BLOCK LENGTH"を変更)
	 */ /* [EN] Change logical sector length (modify "LOGICAL BLOCK LENGTH" in Block Descriptor) */
	uint8_t cdb[kCdbLength10] = {0};
	uint8_t xfrData[klSizeOfBlockDescriptor] = {0};
	
	/* Mode SenseコマンドでBlock Descriptorのカレント値を読み込み */ /* [EN] Read current value of Block Descriptor using Mode Sense command */
	cdb[0] = 0x5A;
	cdb[1] = 0x10;	/* LLBAA(Long LBA)=1, DBD=0 */
	cdb[8] = klSizeOfBlockDescriptor;
	pCommand->setCdb(cdb, kCdbLength10);
	pCommand->setXfrData(xfrData, klSizeOfBlockDescriptor);
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdModeSenseBlock2);
		panic(0);
	}
	
	/* Block Descriptorのカレント値を書換え */ /* [EN] Overwrite the current value of Block Descriptor */
	xfrData[0] = 0;	/* ここの「ブロックディスクリプタ長」(H)はクリア必須 */ /* [EN] The "Block Descriptor length" (H) must be cleared here */
	xfrData[1] = 0;	/* ここの「ブロックディスクリプタ長」(L)はクリア必須 */ /* [EN] The "Block Descriptor length" (L) here must be cleared */
	for(int32_t i = 0; i < 8; i++)	/* データブロック数をAll FFには必須 */ /* [EN] Setting data block count to all FF is required */
	{
		xfrData[8 + i] = 0xFF;
	}
	setBigEndianLWORD(&xfrData[20], logicalSize);	/* "LOGICAL BLOCK LENGTH"(Offset20-23)を変更 */ /* [EN] Change "LOGICAL BLOCK LENGTH" (Offset 20-23) */
	
	/* Mode Selectコマンド(セーブ無し)で装置のBlock Descriptorを変更 */ /* [EN] Change the device's Block Descriptor using Mode Select command (no save) */
	cdb[0] = 0x55;
	cdb[1] = 0x10;	/* PF=1 */
	cdb[8] = klSizeOfBlockDescriptor;
	pCommand->setCdb(cdb, kCdbLength10);
	pCommand->setXfrData(xfrData, klSizeOfBlockDescriptor);
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdModeSelectBlock);
		panic(0);
	}
}

/*--------------------------------------------------------------------------------
 * Position Calculateコマンドを発行し、データ内位置・長さを標準SFI変換する
 *------------------------------------------------------------------------------*/ /* [EN] Issue Position Calculate command and convert data position and length using standard SFI conversion */
void Blocks::issuePositionCalculate(
	int32_t cyl, uint8_t head, uint16_t sct, bool isSectorFull, uint32_t& pos, uint16_t& length)
{
	uint8_t cdb[kCdbLength] = {
		0xE4,
		mServoFormatF ? kBYTEBitNumber1 : 0,	/* Servo=?, Mode=0固定 */ /* [EN] Servo=?, Mode fixed to 0 */
		static_cast<uint8_t>((cyl >> 24) & kMask_7_0),
		static_cast<uint8_t>((cyl >> 16) & kMask_7_0),
		static_cast<uint8_t>((cyl >> 8) & kMask_7_0),
		static_cast<uint8_t>(cyl & kMask_7_0),
		head,
		0,
		static_cast<uint8_t>((sct >> 8) & kMask_7_0),
		static_cast<uint8_t>(sct & kMask_7_0),
		static_cast<uint8_t>((pos >> 8) & kMask_7_0),
		static_cast<uint8_t>(pos & kMask_7_0),
		static_cast<uint8_t>((length >> 8) & kMask_7_0),
		static_cast<uint8_t>(length & kMask_7_0),
		0,
		0
	};
	
	struct PositionCalculateResult
	{
		uint8_t position[4];		/**< 0x00～0x03: Pos 1 */
		uint8_t length[2];			/**< 0x04～0x05: Len 1 */
		uint8_t noCare[22];			/**< 0x06～0x1B: (No Care) */
		uint8_t splitDataLen1[2];	/**< 0x1C～0x1D: Split Data */
		uint8_t dataSFI1[4];		/**< 0x1E～0x21: SECTOR-TOP1 */
		uint8_t dataLen1[2];		/**< 0x22～0x23: SECTOR-LEN1 */
		uint8_t dataSFI2[4];		/**< 0x24～0x27: SECTOR-TOP2 */
		uint8_t dataLen2[2];		/**< 0x28～0x29: SECTOR-LEN2 */
		uint8_t defectScanLen[2];	/**< 0x2A～0x2B: DefectScan-LEN (バイト数) */ /* [EN] 0x2A～0x2B: DefectScan-LEN (byte count) */
	} result;
	
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(&result), sizeof(PositionCalculateResult));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdPositionCalc);
		panic(0);
	}
	
	/* コマンド出力結果を整理 */ /* [EN] Organize command output results */
	if(mServoFormatF)
	{
		/* Servo Format(Tone Scan)の場合 */ /* [EN] In case of Servo Format (Tone Scan) */
		if(isSectorFull)
		{
			pos = getBigEndianLWORD(result.dataSFI1);
			
			/* byte → symbol変換コマンド */ /* [EN] byte to symbol conversion command */
			uint32_t byteValue = getBigEndianWORD(result.defectScanLen);
			memset(cdb, 0, kCdbLength);
			cdb[0] = 0xE9;
			cdb[1] = 0x71;
			cdb[6] = kBYTEBitNumber1;
			cdb[7] = static_cast<uint8_t>((byteValue >> 24) & kMask_7_0);
			cdb[8] = static_cast<uint8_t>((byteValue >> 16) & kMask_7_0);
			cdb[9] = static_cast<uint8_t>((byteValue >> 8) & kMask_7_0);
			cdb[10] = static_cast<uint8_t>(byteValue & kMask_7_0);
			uint32_t symbolValueBigEndian;
			pCommand->setCdb(cdb, kCdbLength);
			pCommand->setXfrData(reinterpret_cast<uint8_t*>(&symbolValueBigEndian), sizeof(uint32_t));
			if(!pCommand->run())
			{
				pCommand->forceDisplay();
				pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdSfi2Bfi2);
				panic(0);
			}
			
			length = swap32(symbolValueBigEndian);
		}
		else
		{
			pos = getBigEndianLWORD(result.position);
			length = getBigEndianWORD(result.length);
		}
	}
	else
	{
		/* Servo Formatでなければ、Sector Full固定 */ /* [EN] If not Servo Format, Sector Full is fixed */
		pos = getBigEndianLWORD(result.dataSFI1);	/* 潜在バグ修正 (#15370) */ /* [EN] Potential bug fix (#15370) */
		if(getBigEndianWORD(result.splitDataLen1) > 0)	/* Split？ */
		{
			length = getBigEndianLWORD(result.dataSFI2) + getBigEndianWORD(result.dataLen2) - pos;
		}
		else
		{
			length = getBigEndianWORD(result.dataLen1);
		}
	}
	
	/* Zone 0, 標準BPI変換 */ /* [EN] Zone 0, standard BPI conversion */
	cnvStandardBPI(cyl, head, pos, length);
}

/*--------------------------------------------------------------------------------
 * Cylinder/Offset値変換コマンドを発行し、シリンダ番号の物理⇔STW変換値を返す
 *------------------------------------------------------------------------------*/ /* [EN] Issue Cylinder/Offset conversion command and return the physical ⇔ STW conversion value of the cylinder number */
int32_t Blocks::issueConvertCylinder(int32_t cyl, uint8_t head, bool isInvert)
{
	uint8_t cdb[kCdbLength] = {0};
	cdb[0] = 0xE9;
	cdb[1] = 0x70;
	cdb[3] = static_cast<uint8_t>((cyl >> 16) & kMask_7_0);
	cdb[4] = static_cast<uint8_t>((cyl >> 8) & kMask_7_0);
	cdb[5] = static_cast<uint8_t>(cyl & kMask_7_0);
	cdb[6] = head;
	cdb[7] = isInvert ? kBYTEBitNumber0 : 0;
	cdb[9] = head;
	
	uint8_t result[0x0C];
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(result, 0x0C);
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdCylinderOffset);
		panic(0);
	}
	
	return getBigEndian3BytesInteger(&result[0]);
}

/*--------------------------------------------------------------------------------
 * 装置の物理アクセス用変数再計算
 *------------------------------------------------------------------------------*/ /* [EN] Recalculate physical access parameter for device */
void Blocks::recalculatePhysicalAccessParameter(uint8_t head, uint8_t zone)
{
	uint8_t cdb[kCdbLength] = {0};
	
	if(zone == kSASegmentNumber)
	{
		zone = getFirmwareSaZoneNumber();
	}
	
	cdb[0] = 0xE9;
	cdb[1] = 0xD2;
	*(reinterpret_cast<uint16_t*>(&cdb[2])) = 0x000D;
	cdb[4] = head;
	cdb[5] = zone;
	pCommand->setCdb(cdb, kCdbLength);
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdTpFuncRebuildBlocks);
		panic(0);
	}
	
	/* フォーマット情報取得 - Page0, Page6 */ /* [EN] Retrieve format information - Page0, Page6 */
	updateFormatInformationPage0();
	updateFormatInformationPage6();
}

/*--------------------------------------------------------------------------------
 * Cylinder/Offset値変換コマンドを発行し、STWシリンダ⇔コアずれ補正値を返す(#84882)
 *------------------------------------------------------------------------------*/ /* [EN] Issue cylinder/offset conversion command and return STW cylinder ⇔ core offset correction value (#84882) */
uint16_t Blocks::getYawValueFromStwCyl(int32_t cyl, uint8_t head)
{
	uint8_t cdb[kCdbLength] = {0};
	cdb[0] = 0xE9;
	cdb[1] = 0x70;
	cdb[3] = static_cast<uint8_t>((cyl >> 16) & kMask_7_0);
	cdb[4] = static_cast<uint8_t>((cyl >> 8) & kMask_7_0);
	cdb[5] = static_cast<uint8_t>(cyl & kMask_7_0);
	cdb[6] = head;
	cdb[7] = kBYTEBitNumber7; /* Yaw bit */
	cdb[9] = head;
	
	uint8_t result[0x0C];
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(result, 0x0C);
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdCylinderOffset2);
		panic(0);
	}
	
	return getBigEndianWORD(&result[0x06]);
}

/*--------------------------------------------------------------------------------
 * コア幅＋指定拡張幅算出＆取得 (Write Post Code同時HDIs Scan用)(#84882)
 *------------------------------------------------------------------------------*/ /* [EN] Calculate and obtain core width plus specified expansion width for simultaneous HDIs scan with Write Post Code (#84882) */
uint32_t Blocks::getCoreWidth(int32_t cyl, uint8_t head, bool& isMinusOD)
{
	/* 物理→STWシリンダ変換 */ /* [EN] Physical to STW Cylinder conversion */
	int32_t stwCyl = issueConvertCylinder(cyl, head, false);
	
	/* STWシリンダ→コアずれ補正値変換 */ /* [EN] Convert STW cylinder to core offset correction value */
	uint16_t stwCoreWidthUint = getYawValueFromStwCyl(stwCyl, head);	/* ※本当はsigned */ /* [EN] Actually signed */
	
	/* シリンダ幅に変換 */ /* [EN] Convert to cylinder width */
	uint32_t coreWide = stwCoreWidthUint;
	int16_t stwCoreWidth = static_cast<int16_t>(stwCoreWidthUint);
	isMinusOD = false;
	if(stwCoreWidth < 0)
	{
		isMinusOD = true;
		stwCoreWidth *= -1;
		coreWide = stwCoreWidth;
	}
	
	double workCoreWide = static_cast<double>(coreWide);

	workCoreWide *= getNormalTPI();
	workCoreWide *= pDrivePrm->getCellSize(head, getZoneNum(cyl, head));

	workCoreWide /= pDrivePrm->getNormalCellSize();
	workCoreWide /= getSTWTPI();	/* STW-TPIで割る */ /* [EN] Divide by STW-TPI */
	workCoreWide /= 0x100;	/* ※1/256cyl単位だから */ /* [EN] Unit is 1/256 cylinder */
	return static_cast<uint32_t>(workCoreWide + 0.999999);	/* 切上げ */ /* [EN] Round up */

}

/*--------------------------------------------------------------------------------
 * DCylのCell Size基準値をドラパラから取得して更新
 *------------------------------------------------------------------------------*/ /* [EN] Update DCyl Cell Size standard value from Drapara */
void Blocks::updateDCylCellSize(void)
{
	ReadWriteParameterUser* pRWPrmUser = pDrivePrm->getPointerOfReadWriteParameterUser();
	mDCylCellSize = pRWPrmUser->getDCylCellSize();
	
	/* TP Defect Map用Cylinderの最大値チェック */ /* [EN] Check the maximum value of Cylinder for TP Defect Map */
	uint32_t totalNumberOfCells = pDrivePrm->getTheNumberOfDataCells() + 1;	/* ※交代用スペア分 +1 */ /* [EN] TP Defect Map use Cylinder maximum value check including spare +1 */
	debugPrint("Total number of cells  : %d\n", totalNumberOfCells);
	debugPrint("DCYL scale rate        : %d\n", mDCylCellSize);
	int32_t maxDCyl = totalNumberOfCells * mDCylCellSize - 1;
	debugPrint("DCYL maximum value     : %08Xh\n", maxDCyl);
	panic(maxDCyl <= kDCylMax);
}

/*--------------------------------------------------------------------------------
 * 実CYL → DCYL 変換
 *------------------------------------------------------------------------------*/ /* [EN] Actual CYL to DCYL conversion */
int32_t Blocks::cyl2dcyl(uint8_t head, int32_t cyl)
{
	if(cyl < 0 || mIsAllZoneDcylTpi)	/* SA Cylinderはそのまま返す */ /* [EN] Return SA Cylinder as is */
	{
		return cyl;
	}
	
	/* cylのCell番号を計算 */ /* [EN] Calculate the Cell number for cyl */
	int32_t cellNumber = 0;
	uint8_t zone = getZoneNum(cyl, head);
	uint32_t cellSize = pDrivePrm->getCellSize(head, zone);
	for(uint8_t forwardZone = 0; forwardZone < zone; forwardZone++)
	{
		cellNumber += pDrivePrm->getNumberOfCells(forwardZone);
	}
	
	int32_t topCylOfZone = getZnSttCyl(zone, head);
	cellNumber += (cyl - topCylOfZone) / cellSize;
	
	/* cylのCell番号に標準TPIのCell Sizeを掛けてdcylに変換 */ /* [EN] Convert the Cell number of cyl to dcyl by multiplying with standard TPI's Cell Size */
	int32_t dcyl = cellNumber * mDCylCellSize;
	
	/* 割り切れない余りのcyl部分を微調整 */ /* [EN] Adjust the remainder part of cyl that does not divide evenly */
	uint32_t remainCyls = (cyl - topCylOfZone) % cellSize;
	if(remainCyls != 0)
	{
		if(cellSize == mDCylCellSize)
		{
			dcyl += remainCyls;
		}
		else
		{
			dcyl += mDCylCellSize * remainCyls / cellSize + 1;
		}
	}
	
	return dcyl;
}

/*--------------------------------------------------------------------------------
 * DCYL → 実CYL 変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert DCYL to actual CYL */
int32_t Blocks::dcyl2cyl(uint8_t head, int32_t dcyl)
{
	if(dcyl < 0 || mIsAllZoneDcylTpi)	/* SA Cylinderはそのまま返す */ /* [EN] Return SA Cylinder as is */
	{
		return dcyl;
	}
	
	/* dcylが属するZone番号を探す */ /* [EN] Find the Zone number that dcyl belongs to */
	uint32_t cellNumber = dcyl / mDCylCellSize;
	uint32_t workCellCount = 0;
	uint8_t zone = 0;
	for( ; zone < (kNumberOfMaxZones - 1); zone++)
	{
		uint32_t numberOfCells = pDrivePrm->getNumberOfCells(zone);
		workCellCount += numberOfCells;
		if(cellNumber < workCellCount)
		{
			workCellCount -= numberOfCells;
			break;
		}
	}
	
	/* dcylが属するZoneの開始Cell番号からのIndexを確定 */ /* [EN] Determine the index from the starting Cell number of the Zone that dcyl belongs to */
	uint32_t indexFromZoneTop = cellNumber - workCellCount;
	
	/* Zoneの開始cylから実cyl位置までのdcyl換算値を加算 */ /* [EN] Add the dcyl equivalent value from the start cyl of the Zone to the actual cyl position */
	uint32_t cellSize = pDrivePrm->getCellSize(head, zone);
	int32_t cyl = getZnSttCyl(zone, head);
	cyl += indexFromZoneTop * cellSize;
	cyl += ((dcyl % mDCylCellSize) * cellSize) / mDCylCellSize;
	
	return cyl;
}

/*--------------------------------------------------------------------------------
 * 全ヘッド・全ゾーンをDCYL基準のTPIに変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert TPI to DCYL standard for all heads and all zones */
void Blocks::convertDCylTpi(void)
{
	TrackPitchTable trackPitchTbl;
	trackPitchTbl.open();
	
	#if defined Switch_Hybrid
	trackPitchTbl.changeCellSizeAll(mDCylCellSize, true);	/* LBA-SA/MCのZone0,1も含めて変更 (#15966) */ /* [EN] Change LBA-SA/MC Zone0 and Zone1 as well (#15966) */
	#else
	trackPitchTbl.changeCellSizeAll(mDCylCellSize);
	#endif
	
	mIsAllZoneDcylTpi = true;
	debugPrint("Convert all zones to DCYL TPI (%d)\n", mDCylCellSize);
}

/*--------------------------------------------------------------------------------
 * 全ヘッド・全ゾーンを元のTPIに戻す
 *------------------------------------------------------------------------------*/ /* [EN] Revert all heads and all zones to the original TPI */
void Blocks::revertDCylTpi(void)
{
	TrackPitchTable trackPitchTbl;
	trackPitchTbl.open();
	trackPitchTbl.revertDefault();
	pDrivePrm->transferToServo(kDriveParameterTrackPitch);
	resetGeometryTbl();
	mIsAllZoneDcylTpi = false;
	debugPrint("Revert all zones to each TPI\n");
}

/*--------------------------------------------------------------------------------
 * 実CYL → DCYL最小値 変換
 *------------------------------------------------------------------------------*/ /* [EN] Convert actual CYL to minimum DCYL */
int32_t Blocks::cyl2dcylMinimum(uint8_t head, int32_t cyl)
{
	uint32_t cellSize = pDrivePrm->getCellSize(head, getZoneNum(cyl, head));
	uint32_t range = ((mDCylCellSize + cellSize - 1) / cellSize) - 1;
	int32_t dcyl = cyl2dcyl(head, cyl);
	for(int32_t i = 0 - range; i < 0; i++)
	{
		if(dcyl2cyl(head, dcyl + i) == cyl)
		{
			return dcyl + i;
		}
	}
	
	return dcyl;
}

/*--------------------------------------------------------------------------------
 * DCYL → 実CYLに変換するための乗数を取得
 *------------------------------------------------------------------------------*/ /* [EN] Get the multiplier to convert DCYL to actual CYL */
double Blocks::getDCyl2CylMultiplier(uint8_t head, uint8_t zone)
{
	double ratio = pDrivePrm->getCellSize(head, zone);
	ratio /= mDCylCellSize;
	return ratio;
}

/*--------------------------------------------------------------------------------
 * (Unit Test) DCYL変換関数の論理テスト
 *------------------------------------------------------------------------------*/ /* [EN] Unit Test for logical testing of the DCYL conversion function */
void Blocks::dcyl_UnitTest(void)
{
	ReadWriteParameterUser* pRWPrmUser = pDrivePrm->getPointerOfReadWriteParameterUser();
	uint16_t minCellSize = pRWPrmUser->getMinCellSize();
	disp();
//	convertDCylTpi();
//	disp();
	
	uint32_t t0 = pSystem->getTimeSecond();
	uint8_t head = 1;
	int32_t cyl1, cyl2, dcyl;
	
	for(int zone = 0; zone < kNumberOfMaxZones; zone++)
	{
		forcePrint("zone %2d\n", zone);
		pDrivePrm->changeCellSize(
			head,
			zone,
			minCellSize + (rand() % (mDCylCellSize - minCellSize + 1)));
		
		int32_t base = getZnSttCyl(zone, head);
		int32_t range = getZnEndCyl(zone, head) - base + 1;
		for(int i = 0; i < range; i += 250)
		{
			cyl1 = base + i;
			dcyl = cyl2dcyl(head, cyl1);
			cyl2 = dcyl2cyl(head, dcyl);
			forcePrint(" cyl:%7d -> dcyl:%7d -> cyl:%7d", cyl1, dcyl, cyl2);
			if(cyl1 != cyl2)
			{
				forcePrint(" NG!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n");
			}
			else
			{
				forcePrint(" OK\n");
			}
		}
	}
	
	forcePrint("time : %dsec.\n", pSystem->getTimeSecond() - t0);
//	disp();
	revertDCylTpi();
	disp();
}

#if !defined Switch_NotSupportedAreaSkip
/*--------------------------------------------------------------------------------
 * フォーマット情報取得 - Page12 (更新)
 *------------------------------------------------------------------------------*/ /* [EN] Update Format Information - Page 12 */
void Blocks::updateFormatInformationPage12(void)
{
	FormatInformationPage12* pPage12Local
		= reinterpret_cast<FormatInformationPage12*>(mPage12TagCmr.getMemoryAccessBegin());
	#if defined Switch_Hybrid
	if(pDisk->isSmr())
	{
		pPage12Local = reinterpret_cast<FormatInformationPage12*>(mPage12TagSmr.getMemoryAccessBegin());
	}
	#endif
	
	/* フォーマット情報取得 - Page12 */ /* [EN] Retrieve format information - Page 12 */
	uint8_t cdb[kCdbLength] = { 0xE9, 0x72, 0x0C, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
	pCommand->setCdb(cdb, kCdbLength);
	pCommand->setXfrData(reinterpret_cast<uint8_t*>(pPage12Local), sizeof(FormatInformationPage12));
	if(!pCommand->run())
	{
		pCommand->forceDisplay();
		pLog->getSeqLogObj()->forceStopLog(kFatalErrCmdFormatInfoPage12);
		panic(0);
	}
	
	if(strncmp(pPage12Local->headerId, "ENCL", 4) == 0)
	{
		#if defined Switch_Hybrid
		if(pDisk->isSmr())
		{
			pPage12Smr = pPage12Local;
			debugPrint("[Blocks::updateFormatInformationPage12] SMR\n");
		}
		else
		#endif
		{
			pPage12Cmr = pPage12Local;
			debugPrint("[Blocks::updateFormatInformationPage12] CMR\n");
		}
	}
	
	dumpMemory(reinterpret_cast<uint8_t*>(pPage12Local), 0x50);
	debugPrint("hd, seg, enable cyl-range\n");
	for(int head = 0; head < getHeadCnt(); head++)
	{
		for(int segment = 0; segment < kMaxNumberOfUserSegments; segment++)
		{
			int32_t cylTop = static_cast<int32_t>(swap32(pPage12Local->enableArea[segment][head].startCylNum));
			int32_t cylEnd = cylTop + swap32(pPage12Local->enableArea[segment][head].numberOfCyls) - 1;
			debugPrint("%2d, %3d, 0x%08X - 0x%08X\n", head, segment, cylTop, cylEnd);
		}
	}
}

/*--------------------------------------------------------------------------------
 * フォーマット情報Page12をクリア
 *------------------------------------------------------------------------------*/ /* [EN] Clear format information Page12 */
void Blocks::clearFormatInformationPage12(void)
{
	if(pPage12Cmr != NULL)
	{
		mPage12TagCmr.fill(0);
		pPage12Cmr = NULL;
	}
	
	#if defined Switch_Hybrid
	if(pPage12Smr != NULL)
	{
		mPage12TagSmr.fill(0);
		pPage12Smr = NULL;
	}
	#endif
}

/*--------------------------------------------------------------------------------
 * フォーマット情報Page12(CMR用)を指定Bufferからコピー (Load処理)
 *------------------------------------------------------------------------------*/ /* [EN] Copy format information Page12 (for CMR) from specified buffer (load process) */
void Blocks::loadFormatPage12Cmr(Tag* pTag, uint32_t offset)
{
	mPage12TagCmr.move(*pTag, offset, 0, sizeof(FormatInformationPage12));
	FormatInformationPage12* pPage12Local
		= reinterpret_cast<FormatInformationPage12*>(mPage12TagCmr.getMemoryAccessBegin());
	if(strncmp(pPage12Local->headerId, "ENCL", 4) == 0)
	{
		pPage12Cmr = pPage12Local;
	}
}

/*--------------------------------------------------------------------------------
 * フォーマット情報Page12(CMR用)を指定Bufferへコピー (Save処理)
 *------------------------------------------------------------------------------*/ /* [EN] Copy format information Page12 (for CMR) to specified buffer (Save process) */
void Blocks::saveFormatPage12Cmr(Tag* pTag, uint32_t offset)
{
	if(pPage12Cmr != NULL)
	{
		pTag->move(mPage12TagCmr, 0, offset, sizeof(FormatInformationPage12));
	}
}

#if defined Switch_Hybrid
/*--------------------------------------------------------------------------------
 * フォーマット情報Page12(SMR用)を指定Bufferからコピー (Load処理)
 *------------------------------------------------------------------------------*/ /* [EN] Copy format information Page12 (for SMR) from specified buffer (load process) */
void Blocks::loadFormatPage12Smr(Tag* pTag, uint32_t offset)
{
	mPage12TagSmr.move(*pTag, offset, 0, sizeof(FormatInformationPage12));
	FormatInformationPage12* pPage12Local
		= reinterpret_cast<FormatInformationPage12*>(mPage12TagSmr.getMemoryAccessBegin());
	if(strncmp(pPage12Local->headerId, "ENCL", 4) == 0)
	{
		pPage12Smr = pPage12Local;
	}
}

/*--------------------------------------------------------------------------------
 * フォーマット情報Page12(SMR用)を指定Bufferへコピー (Save処理)
 *------------------------------------------------------------------------------*/ /* [EN] Copy format information Page12 (for SMR) to specified buffer (Save process) */
void Blocks::saveFormatPage12Smr(Tag* pTag, uint32_t offset)
{
	if(pPage12Smr != NULL)
	{
		pTag->move(mPage12TagSmr, 0, offset, sizeof(FormatInformationPage12));
	}
}
#endif

/*--------------------------------------------------------------------------------
 * 引数で指定されたトラックがエリアスキップ対象か判定する
 *------------------------------------------------------------------------------*/ /* [EN] Determine if the track specified by the arguments is a target for area skip */
bool Blocks::isInAreaSkip(int32_t cyl, uint8_t head)
{
	FormatInformationPage12* pPage12Local = pPage12Cmr;
	#if defined Switch_Hybrid
	if(pDisk->isSmr())
	{
		pPage12Local = pPage12Smr;
	}
	#endif
	
	if(pPage12Local != NULL && cyl >= 0)
	{
		/* 対象となるSegment番号 */ /* [EN] Target Segment number */
		uint8_t segmentTop = getSegmentNum(cyl, head);	/* ※Zoneモード時はZone番号になる */ /* [EN] In Zone mode, it becomes the Zone number */
		uint8_t segmentEnd = segmentTop;
		if(!isSegmentMode())
		{
			/* Zoneモード時は対象となるSegment番号が対象Zoneに含まれる範囲 */ /* [EN] In Zone mode, the target Segment number is within the range of the target Zone. */
			segmentTop *= kNumberOfSegmentsPerZone;
			segmentEnd = segmentTop + kNumberOfSegmentsPerZone - 1;
		}
		
		/* 有効エリアに含まれているかチェック */ /* [EN] Check if included in the enable area */
		for(int segment = segmentTop; segment <= segmentEnd; segment++)
		{
			int32_t cmprCylTop
				= static_cast<int32_t>(swap32(pPage12Local->enableArea[segment][head].startCylNum));
			int32_t cmprCylEnd
				= cmprCylTop + swap32(pPage12Local->enableArea[segment][head].numberOfCyls) - 1;
			
			if(segment == (kMaxNumberOfUserSegments - 1))
			{
				/* ※最終Segmentの場合、スペアが含まれないので最Inner cylに置き換える */ /* [EN] For the final segment, replace with the innermost cylinder since spares are not included. */
				cmprCylEnd = getMaxCylNum(head);
			}
			
			if(cyl >= cmprCylTop && cyl <= cmprCylEnd)
			{
				return false;	/* 有効エリアに含まれている */ /* [EN] Included in the effective area */
			}
		}
		
		return true;	/* 有効エリアに含まれていないのでスキップ対象 */ /* [EN] Not included in the valid area, so skip target */
	}
	
	return false;
}

/*--------------------------------------------------------------------------------
 * 幅狭特殊Zoneかを判定
 *------------------------------------------------------------------------------*/ /* [EN] Determine if it is a narrow special Zone */
bool Blocks::isSpecialZone(uint8_t zone)
{
	if(isSegmentMode())
	{
		/* Segmentモードの場合、Cell数が0のSegmentが存在するZoneを幅狭特殊Zoneとする */ /* [EN] In segment mode, a zone with segments having zero cells is considered a narrow special zone */
		uint8_t segment = zone2Segment(zone, 0);
		for(int relative = 0; relative < kNumberOfSegmentsPerZone; relative++)
		{
			if(swap16(pPage6->userSegmentInformation[segment + relative].numberOfCellsPerSegment) == 0)
			{
				return true;
			}
		}
	}
	else
	{
		/* Zoneモードの場合、Zone当たりの平均Cell数より少ないZoneを幅狭特殊Zoneとする */ /* [EN] In Zone mode, treat zones with fewer cells per zone than the average number of cells per zone as narrow special zones */
		uint32_t aveNumberOfCell = pDrivePrm->getTheNumberOfDataCells() / kNumberOfMaxZones;
		if(swap16(pPage6->userSegmentInformation[zone].numberOfCellsPerSegment) < aveNumberOfCell)
		{
			return true;
		}
	}
	
	return false;
}
#endif	/* !defined Switch_NotSupportedAreaSkip */

/*--------------------------------------------------------------------------------
 * 指定HeadのMedia Bump登録数を取得
 *------------------------------------------------------------------------------*/ /* [EN] Retrieve the number of Media Bumps registered for the specified Head */
uint32_t Blocks::getNumberOfMediaBumps(uint8_t head)
{
	uint32_t bumpCnt = 0;
	for(int segment = 0; segment < kMaxNumberOfUserSegments; segment++)
	{
		bumpCnt += swap16(pPage6->userSegmentInformation[segment].numberOfMediaBumps[head]);
	}
	
	return bumpCnt;
}

/*--------------------------------------------------------------------------------
 * Blocks情報をUART出力表示
 *------------------------------------------------------------------------------*/ /* [EN] Display Blocks information via UART output */
void Blocks::disp(void)
{
	uint8_t numberOfSegment = getZoneCnt();
	if(isSegmentMode())
	{
		numberOfSegment = kMaxNumberOfUserSegments;
		debugPrint("\nHead, Zone, Segment, BPI, TPI,CELL,   CYL-TOP,   CYL-END, SCTs/TRK, Symbols/TRK\n");
	}
	else
	{
		debugPrint("\nHead, Zone, BPI, TPI,CELL,   CYL-TOP,   CYL-END, SCTs/TRK, Symbols/TRK\n");
	}
	
	HeadSkipTable hsp;
	hsp.open();
	
	uint8_t headCount = getHeadCnt();
	for(int head = 0; head < headCount; head++)
	{
		if(hsp.isSkipped(head))
		{
			continue;
		}
		
		for(uint8_t segment = 0; segment < numberOfSegment; segment++)
		{
			int32_t cylTop = static_cast<int32_t>(
				swap32(pPage6->userSegmentInformation[segment].startCylinderNumber[head]));
			int32_t cylEnd = cylTop + swap32(pPage6->userSegmentInformation[segment].numberOfCyls[head]) - 1;
			if(isSegmentMode())
			{
				uint8_t zone = segment / kNumberOfSegmentsPerZone;
				debugPrint("  %2d,   %2d,     %3d, %3d,",
					head, zone, segment, pDrivePrm->getBpiType(head, zone));
			}
			else
			{
				debugPrint("  %2d,   %2d, %3d,", head, segment, pDrivePrm->getBpiType(head, segment));
			}
			
			/* 最終Zone or 最終Segmentの場合、最終Cylinder番号を未使用のトラックの手前までのCylinder番号とする */ /* [EN] In the final Zone or final Segment, set the final Cylinder number to the Cylinder number just before the unused tracks. */
			if(segment == (numberOfSegment - 1))
			{
				cylEnd = static_cast<int32_t>(swap32(pPage0->numberOfTracksUser[head])) - 1;
			}
			
			debugPrint(" %3d,%4d, 0x%07X, 0x%07X,   0x%04X,  0x%08X\n",
				swap32(pPage6->userSegmentInformation[segment].numberOfTrackInCell[head]),
				swap16(pPage6->userSegmentInformation[segment].numberOfCellsPerSegment),
				cylTop,
				cylEnd,
				getSctsPerTrkCylHd(cylTop, head),
				getSymbolsPerTrack(cylTop, head));
		}
	}
	debugPrint("\n");
}

/*--------------------------------------------------------------------------------
 * Returns Cells Per Zone
 *------------------------------------------------------------------------------*/
uint16_t Blocks::cellsPerZone(uint8_t zone)
{
	return swap16(pPage6->userSegmentInformation[zone].numberOfCellsPerSegment);
}

/*--------------------------------------------------------------------------------
 * Returns Tracks Per Cell
 *------------------------------------------------------------------------------*/
uint32_t Blocks::tracksPerCell(uint8_t head, uint8_t zone)
{
	return swap32(pPage6->userSegmentInformation[zone].numberOfTrackInCell[head]);
}


/*******************************************************************************

                                  NOTICE

                    Copyright (c) 2024 TOSHIBA CORPORATION
                           All rights reserved

 This program is CONFIDENTIAL and a TRADE SECRET of TOSHIBA CORPORATION.
 The receipt or possession of this program does not convey any rights to
 reproduce or disclose its contents, or to manufacture, use, or sell
 anything that it may describe, in whole or in part, without the specific
 written consent of TOSHIBA CORPORATION.  Any reproduction of this program
 without the express written consent of TOSHIBA CORPORATION is a violation
 of the copyright laws and may subject you to criminal prosecution.

********************************************************************************/
