"""mat_editor MOD 导出/导入编排 — MatModIOMixin (T18 自 MatEditorApp 迁出)。

方法体原样迁入, 经 mixin 由 MatEditorApp 继承; 依赖的模块级名字改为显式导入。"""
import base64
import os
import struct

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from mat_constants import DEFUNIT_REC_SIZE, DWORD_COUNT, REC_SIZE
from mat_dat_io import has_data, scene_name
from mat_text_codec import load_tkd, parse_defines
from editor_utils.mod_exporter import (
    ModExportPreviewDialog, ModImportPreviewDialog, ModMetadataDialog,
    build_block_diff_json, build_data_diff_json, build_text_diff_json,
    compute_crc32, diff_records, diff_text_defines, generate_mod_json,
    get_tksmod_info, import_tksmod_records, import_tksmod_text_defines,
    load_reference_dat_fields, pack_tksmod, safe_mod_filename,
)


class MatModIOMixin:
    """.tksmod 导出/导入编排 (四方法自 MatEditorApp 原样迁入)。"""

    def _export_tksmod(self):
        """导出当前修改为 .tksmod MOD 文件 (TKMat + TKDefUnit + TKD 三文件联动)"""
        if not self._data.records or not hasattr(self, '_original_mat_records'):
            QMessageBox.information(self, "提示", "请先加载数据")
            return
        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        data_files = {}
        components = []

        # TKMat.Dat 差异
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self._data.records]
        mat_diff = diff_records(self._original_mat_records, current_mat, DWORD_COUNT, len(self._original_mat_records))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(self._data.dat_path) if self._data.dat_path else "0x00000000"
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(self._original_mat_records), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, '_original_defunit_recs') and hasattr(self, '_data'):
            current_du = self._du_recs_to_full_fields()
            du_diff = diff_records(self._original_defunit_recs, current_du, 8, len(self._original_defunit_recs))
            if du_diff['modified'] or du_diff['appended']:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=len(self._original_defunit_recs), original_crc32=crc, diff_result=du_diff)
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, '_original_tkd_defines') and hasattr(self, '_data'):
            self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
            current_tkd = {
                str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                for dd in self._data.tkd_defines
            }
            tkd_diff = diff_text_defines(self._original_tkd_defines, current_tkd)
            if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与原始文件相同，无需导出。")
            return

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD: {os.path.basename(fp)} ({len(components)}文件, {total}处变更)")
            QMessageBox.information(self, "导出成功", f"已导出:\n{fp}\n\n包含 {len(components)} 个数据文件")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_tksmod_with_ref(self):
        """导出 MOD — 指定原始参考目录进行差异比对 (TKMat + TKDefUnit + TKD)"""
        if not self._data.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        # 先将编辑器中当前 DEFINE 的改动回写, 确保预览统计与实际导出一致
        self._save_editor_to_define()

        # 预构建当前 TKMat 字段
        current_mat = [[r.get(f'd{i}', 0) for i in range(DWORD_COUNT)] for r in self._data.records]

        def _compute_stats(ref_dir):
            ref_mat = load_reference_dat_fields(ref_dir, "TKMat.Dat",
                rec_size=REC_SIZE, field_count=DWORD_COUNT, field_fmt='i', use_lzss=False)
            if ref_mat is None:
                return {"valid": False, "error": "目录中未找到 TKMat.Dat"}
            mat_diff = diff_records(ref_mat, current_mat, DWORD_COUNT, len(ref_mat))
            targets = []
            if mat_diff['modified'] or mat_diff['appended']:
                targets.append({"name": "TKMat.dat",
                    "modified": len(mat_diff['modified']),
                    "appended": len(mat_diff['appended']),
                    "deleted": 0})
            # TKDefUnit.dat (如果可加载)
            du_path = os.path.join(ref_dir, "TKDefUnit.Dat")
            if os.path.isfile(du_path) and hasattr(self, '_data'):
                try:
                    ref_du = load_reference_dat_fields(ref_dir, "TKDefUnit.Dat",
                        rec_size=DEFUNIT_REC_SIZE, field_count=8, field_fmt='H', use_lzss=False)
                    if ref_du is not None:
                        cur_du = self._du_recs_to_full_fields()
                        du_diff = diff_records(ref_du, cur_du, 8, len(ref_du))
                        if du_diff['modified'] or du_diff['appended']:
                            targets.append({"name": "TKDefUnit.dat",
                                "modified": len(du_diff['modified']),
                                "appended": len(du_diff['appended']),
                                "deleted": 0})
                except Exception:
                    pass
            # TKD.dat 脚本差异 (与实际导出逻辑保持一致, 否则预览会漏报脚本改动)
            ref_tkd_path = os.path.join(ref_dir, "TKD.dat")
            if os.path.isfile(ref_tkd_path) and hasattr(self, '_data'):
                try:
                    ref_tkd_text = load_tkd(ref_tkd_path)
                    ref_tkd_defs, _ = parse_defines(ref_tkd_text)
                    ref_tkd_map = {
                        str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                        for dd in ref_tkd_defs
                    }
                    cur_tkd_map = {
                        str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                        for dd in self._data.tkd_defines
                    }
                    tkd_diff = diff_text_defines(ref_tkd_map, cur_tkd_map)
                    if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                        targets.append({"name": "TKD.dat",
                            "modified": len(tkd_diff['modified']),
                            "appended": len(tkd_diff['appended']),
                            "deleted": len(tkd_diff['deleted'])})
                except Exception:
                    pass
            return {"valid": True, "targets": targets}

        preview_dlg = ModExportPreviewDialog(self,
            default_dir=self._get_game_dir(),
            compute_stats=_compute_stats)
        if preview_dlg.exec() != QDialog.Accepted: return
        ref_dir = preview_dlg.get_ref_dir()

        # 加载参考目录中的 TKMat.Dat
        ref_mat = load_reference_dat_fields(ref_dir, "TKMat.Dat",
            rec_size=REC_SIZE, field_count=DWORD_COUNT, field_fmt='i', use_lzss=False)
        if ref_mat is None:
            QMessageBox.warning(self, "参考目录无效", f"在 {ref_dir} 中未找到 TKMat.Dat")
            return

        data_files = {}
        components = []

        # TKMat.Dat 差异
        mat_diff = diff_records(ref_mat, current_mat, DWORD_COUNT, len(ref_mat))
        if mat_diff['modified'] or mat_diff['appended']:
            crc = compute_crc32(os.path.join(ref_dir, "TKMat.Dat"))
            mat_json = build_data_diff_json(target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=len(ref_mat), original_crc32=crc, diff_result=mat_diff)
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # TKDefUnit.Dat 差异
        if hasattr(self, '_data'):
            ref_du = load_reference_dat_fields(ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8, field_fmt='H', use_lzss=False)
            if ref_du is not None:
                current_du = self._du_recs_to_full_fields()
                du_diff = diff_records(ref_du, current_du, 8, len(ref_du))
                if du_diff['modified'] or du_diff['appended']:
                    crc = compute_crc32(os.path.join(ref_dir, "TKDefUnit.Dat"))
                    du_json = build_data_diff_json(target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE,
                        field_type="uint16", field_count=8, original_count=len(ref_du), original_crc32=crc, diff_result=du_diff)
                    data_files["data/TKDefUnit.dat.json"] = du_json
                    components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # TKD.dat 脚本差异
        if hasattr(self, '_data'):
            ref_tkd_path = os.path.join(ref_dir, "TKD.dat")
            if os.path.exists(ref_tkd_path):
                self._save_editor_to_define()  # 确保当前编辑中的脚本已回写
                ref_tkd_text = load_tkd(ref_tkd_path)
                ref_tkd_defs, _ = parse_defines(ref_tkd_text)
                ref_tkd_map = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in ref_tkd_defs
                }
                current_tkd = {
                    str(dd['define_id']): '\r\n'.join([dd['header_line']] + dd['body_lines'])
                    for dd in self._data.tkd_defines
                }
                tkd_diff = diff_text_defines(ref_tkd_map, current_tkd)
                if tkd_diff['modified'] or tkd_diff['appended'] or tkd_diff['deleted']:
                    crc = compute_crc32(ref_tkd_path)
                    tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc, diff_result=tkd_diff)
                    data_files["data/TKD.dat.json"] = tkd_json
                    components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        if not data_files:
            QMessageBox.information(self, "无差异", "当前数据与参考文件相同，无需导出。")
            return

        dlg = ModMetadataDialog(self, getattr(self, '_last_mod_metadata', None))
        if dlg.exec() != QDialog.Accepted: return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        mod_json = generate_mod_json(metadata, components)
        fp, _ = QFileDialog.getSaveFileName(self, "导出为 MOD", f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod", "TKS MOD (*.tksmod)")
        if not fp: return
        try:
            pack_tksmod(fp, mod_json, data_files)
            total = sum(len(v.get('modified', [])) + len(v.get('appended', [])) for v in data_files.values())
            self.status_var.setText(f"已导出 MOD (参考目录): {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", f"已导出 (参考目录模式):\n{fp}\n\n参考: {ref_dir}\n包含 {len(components)} 个数据文件, {total} 处变更")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _export_scene_as_tksmod(self):
        """导出当前场景为 .tksmod MOD 文件 — 直接导出选中场景全部数据（不判断差异）"""
        if not self._data.records:
            QMessageBox.information(self, "提示", "请先加载数据")
            return

        sid = self._canvas._vis_scene_id
        if sid < 0:
            QMessageBox.warning(self, "无效场景", "请先在可视化面板中选择一个场景")
            return

        # ── 1. 筛选属于本场景的实体 ──
        scene_entity_indices = [i for i, r in enumerate(self._data.records)
                                if has_data(r) and r['d1'] == sid]
        if not scene_entity_indices:
            QMessageBox.warning(self, "空场景", f"场景 {sid} 无实体数据")
            return

        # ── 2. 追踪 DefUnit 链 ──
        def find_du(idx):
            return next((r for r in self._data.defunit_recs if r['index'] == idx), None)

        all_defunit_indices = set()

        def collect_chain(head_idx):
            cur = head_idx
            visited = set()
            while cur >= 0 and cur not in visited:
                visited.add(cur)
                du = find_du(cur)
                if du is None:
                    break
                all_defunit_indices.add(cur)
                nxt = du.get('f6', 0)
                if nxt == 0 or nxt in visited:
                    break
                cur = nxt

        for eidx in scene_entity_indices:
            rec = self._data.records[eidx]
            for chain_di, max_di in [(39, 30), (40, 31), (41, 32)]:
                head = rec.get(f'd{chain_di}', -1)
                mx = rec.get(f'd{max_di}', 0)
                if head > 0 and mx > 0:
                    collect_chain(head)

        # ── 3. 追踪 TKD DEFINE 块 ──
        scene_define_ids = set()
        for du_idx in all_defunit_indices:
            du = find_du(du_idx)
            if du:
                did = (du.get('f1', 0) << 16) | du.get('f0', 0)
                if did > 0:
                    scene_define_ids.add(str(did))

        # ── 4. 弹出 MOD 元数据对话框 ──
        sname = scene_name(self._data.tkt_scenes, sid).replace('/', '_').replace('\\', '_')
        defaults = getattr(self, '_last_mod_metadata', None) or {}
        if not defaults.get('id'):
            defaults['id'] = f"scene_{sid}_{sname}"
        if not defaults.get('name'):
            defaults['name'] = f"场景 {sname} (ID={sid})"
        if not defaults.get('type'):
            defaults['type'] = 'story'
        dlg = ModMetadataDialog(self, defaults)
        if dlg.exec() != QDialog.Accepted:
            return
        metadata = dlg.get_metadata()
        self._last_mod_metadata = metadata

        # ── 5. 直接导出 TKMat.Dat 场景实体（全量字段，不做差异比对）──
        data_files = {}
        components = []

        mat_entries = []
        for eidx in scene_entity_indices:
            rec = self._data.records[eidx]
            # 导出所有字段（含零值），确保导入时能完整覆盖目标槽位
            fields = {}
            for fi in range(DWORD_COUNT):
                fields[f"f{fi}"] = rec.get(f'd{fi}', 0)
            mat_entries.append({"index": eidx, "fields": fields})

        if mat_entries:
            crc = compute_crc32(self._data.dat_path) if self._data.dat_path else "0x00000000"
            original_count = len(self._data.records)
            mat_json = build_data_diff_json(
                target="TKMat.Dat", record_size=REC_SIZE, field_type="int32",
                field_count=DWORD_COUNT, original_count=original_count,
                original_crc32=crc, diff_result={'modified': mat_entries, 'appended': []})
            data_files["data/TKMat.dat.json"] = mat_json
            components.append({"file": "data/TKMat.dat.json", "target": "TKMat.Dat"})

        # ── 6. 直接导出 TKDefUnit.Dat（全量字段，不做差异比对）──
        if hasattr(self, '_data') and all_defunit_indices:
            du_entries = []
            for du_idx in sorted(all_defunit_indices):
                du = find_du(du_idx)
                if du:
                    # 导出所有字段（含零值）
                    fields = {}
                    for fi in range(8):
                        fields[f"f{fi}"] = du.get(f'f{fi}', 0)
                    du_entries.append({"index": du_idx, "fields": fields})

            if du_entries:
                du_path = os.path.join(self._get_game_dir(), "TKDefUnit.Dat")
                crc = compute_crc32(du_path) if os.path.exists(du_path) else "0x00000000"
                original_du_count = len(self._data.defunit_recs)
                du_json = build_data_diff_json(
                    target="TKDefUnit.Dat", record_size=DEFUNIT_REC_SIZE, field_type="uint16",
                    field_count=8, original_count=original_du_count,
                    original_crc32=crc, diff_result={'modified': du_entries, 'appended': []})
                data_files["data/TKDefUnit.dat.json"] = du_json
                components.append({"file": "data/TKDefUnit.dat.json", "target": "TKDefUnit.Dat"})

        # ── 7. 直接导出 TKD.dat 脚本（全量内容，不做差异比对）──
        if hasattr(self, '_data') and scene_define_ids:
            self._save_editor_to_define()
            tkd_modified = {}
            for dd in self._data.tkd_defines:
                did_str = str(dd['define_id'])
                if did_str in scene_define_ids:
                    tkd_modified[did_str] = '\r\n'.join([dd['header_line']] + dd['body_lines'])

            if tkd_modified:
                tkd_path = os.path.join(self._get_game_dir(), "TKD.dat")
                crc = compute_crc32(tkd_path) if os.path.exists(tkd_path) else "0x00000000"
                tkd_json = build_text_diff_json(target="TKD.dat", original_crc32=crc,
                    diff_result={'modified': tkd_modified, 'appended': [], 'deleted': []})
                data_files["data/TKD.dat.json"] = tkd_json
                components.append({"file": "data/TKD.dat.json", "target": "TKD.dat"})

        # ── 8. 直接导出 SC.GRP 场景区段（不做差异比对）──
        if self._data.dat_path:
            game_dir = self._get_game_dir()
            grp_path = os.path.join(game_dir, "SC.GRP")
            idx_path = os.path.join(game_dir, "SC.IDX")
            if os.path.exists(grp_path) and os.path.exists(idx_path):
                try:
                    with open(idx_path, 'rb') as f:
                        idata = f.read()
                    offs = [struct.unpack_from('<I', idata, i)[0] for i in range(0, len(idata), 4)]
                    if sid < len(offs):
                        start = offs[sid]
                        end = offs[sid + 1] if sid + 1 < len(offs) else os.path.getsize(grp_path)
                        with open(grp_path, 'rb') as f:
                            f.seek(start)
                            section_data = f.read(end - start)
                        if section_data:
                            total_sections = len(offs) - 1 if len(offs) > 1 else len(offs)
                            sc_diff = {
                                'modified': [{'index': sid, 'data_b64': base64.b64encode(section_data).decode('ascii')}],
                                'appended': [],
                                'deleted_indices': [],
                            }
                            crc = compute_crc32(grp_path)
                            sc_json = build_block_diff_json(
                                target="SC.GRP", block_type="grp_section",
                                original_count=total_sections,
                                original_crc32=crc, diff_result=sc_diff)
                            data_files["data/SC.GRP.json"] = sc_json
                            components.append({"file": "data/SC.GRP.json", "target": "SC.GRP"})
                except Exception:
                    pass

        # ── 9. 最终打包 ──
        if not data_files:
            QMessageBox.information(self, "无数据",
                f"场景 {sid} 未收集到任何可导出数据。")
            return

        # 在 mod.json 中附加 scene_scope 字段
        metadata['scene_scope'] = [sid]
        mod_json = generate_mod_json(metadata, components)
        mod_json['scene_scope'] = [sid]
        mod_json['scene_name'] = scene_name(self._data.tkt_scenes, sid)

        fp, _ = QFileDialog.getSaveFileName(
            self, "导出场景为 MOD",
            f"{safe_mod_filename(metadata['name'], metadata['id'])}.tksmod",
            "TKS MOD (*.tksmod);;所有文件 (*.*)")
        if not fp:
            return
        try:
            pack_tksmod(fp, mod_json, data_files)
            n_mat = len(mat_entries)
            n_du = len(data_files.get('data/TKDefUnit.dat.json', {}).get('modified', []))
            n_tkd = len(data_files.get('data/TKD.dat.json', {}).get('modified', {}))
            has_sc = 'data/SC.GRP.json' in data_files
            summary = (f"场景 {scene_name(self._data.tkt_scenes, sid)} (ID={sid})\n"
                       f"实体: {n_mat} 条\n"
                       f"DefUnit: {n_du} 条\n"
                       f"脚本: {n_tkd} 块\n"
                       f"SC.GRP: {'包含' if has_sc else '无'}\n\n"
                       f"已保存到:\n{fp}")
            self.status_var.setText(f"已导出场景 MOD: {os.path.basename(fp)}")
            QMessageBox.information(self, "导出成功", summary)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _import_tksmod(self):
        """从 .tksmod 导入 MOD 数据到编辑器 (TKMat + TKDefUnit + TKD 三文件联动)"""
        fp, _ = QFileDialog.getOpenFileName(self, "选择 MOD 文件", "", "TKS MOD (*.tksmod)")
        if not fp: return

        info = get_tksmod_info(fp)
        if info is None:
            QMessageBox.warning(self, "无效文件", "无法解析此 .tksmod 文件")
            return

        # 检查是否包含相关数据
        targets = info.get("targets", [])
        has_mat = "TKMat.Dat" in targets
        has_du = "TKDefUnit.Dat" in targets
        has_tkd = "TKD.dat" in targets
        has_sc = "SC.GRP" in targets
        if not has_mat and not has_du and not has_tkd and not has_sc:
            QMessageBox.warning(self, "不兼容",
                "此 MOD 不包含 TKMat/TKDefUnit/TKD/SC.GRP 的数据\n\n"
                f"包含的数据: {', '.join(targets)}")
            return

        dlg = ModImportPreviewDialog(self, info, default_dir=self._get_game_dir())
        if dlg.exec() != QDialog.Accepted: return
        ref_dir = dlg.get_ref_dir()
        if not ref_dir: return

        imported_parts = []

        # 导入 TKMat.Dat
        if has_mat:
            mod_json, mat_records = import_tksmod_records(
                fp, ref_dir, "TKMat.Dat",
                rec_size=REC_SIZE, field_count=DWORD_COUNT,
                field_fmt='i', use_lzss=False
            )
            if mat_records is not None:
                new_records = []
                for i, fields in enumerate(mat_records):
                    rec = {'index': i}
                    for di in range(DWORD_COUNT):
                        rec[f'd{di}'] = fields[di] if di < len(fields) else 0
                    rec['_has_data'] = any(rec[f'd{di}'] for di in range(DWORD_COUNT))
                    new_records.append(rec)
                self._data.records = new_records
                self._original_mat_records = [list(row) for row in mat_records]
                imported_parts.append(f"TKMat ({len(mat_records)}条)")

        # 导入 TKDefUnit.Dat
        if has_du:
            _, du_records = import_tksmod_records(
                fp, ref_dir, "TKDefUnit.Dat",
                rec_size=DEFUNIT_REC_SIZE, field_count=8,
                field_fmt='H', use_lzss=False
            )
            if du_records is not None and hasattr(self, '_data'):
                new_du = []
                for i, fields in enumerate(du_records):
                    rec = {'index': i}
                    for fi in range(8):
                        rec[f'f{fi}'] = fields[fi] if fi < len(fields) else 0
                    new_du.append(rec)
                self._data.defunit_recs = new_du
                self._original_defunit_recs = [list(row) for row in du_records]
                imported_parts.append(f"TKDefUnit ({len(du_records)}条)")

        # 导入 TKD.dat
        if has_tkd:
            _, defines = import_tksmod_text_defines(fp, ref_dir)
            if defines is not None and hasattr(self, '_data'):
                # 将 defines dict 转化为编辑器内部 tkd_defines 格式
                new_tkd = []
                for did_str, content in sorted(defines.items(),
                        key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                    lines = content.split('\r\n') if '\r\n' in content else content.split('\n')
                    header_line = lines[0] if lines else ''
                    body_lines = lines[1:] if len(lines) > 1 else []
                    new_tkd.append({
                        'define_id': int(did_str) if did_str.isdigit() else 0,
                        'header_line': header_line,
                        'body_lines': body_lines,
                    })
                self._data.tkd_defines = new_tkd
                self._data.tkd_define_map = {dd['define_id']: dd for dd in new_tkd}
                self._original_tkd_defines = dict(defines)
                imported_parts.append(f"TKD ({len(new_tkd)}块)")
                # 刷新脚本编辑器
                self._current_edit_define_id = None

        # 导入 SC.GRP（只存入内存，等用户保存时才写入文件）
        if has_sc:
            # 先加载原始块列表，再应用diff
            from editor_utils.mod_exporter import load_grp_raw_sections
            ref_sc_path = os.path.join(ref_dir, "SC.GRP")
            sc_blocks = load_grp_raw_sections(ref_sc_path)
            if sc_blocks is not None:
                # 检查 scene_scope 中是否有超出原始范围的场景索引
                scene_scope = info.get('scene_scope', [])
                if scene_scope:
                    max_idx = max(scene_scope)
                    # 扩展 sc_blocks 数组以容纳最大索引
                    while len(sc_blocks) <= max_idx:
                        sc_blocks.append(b'')  # 空区段占位

                # 现在应用 diff
                import base64 as b64
                import json
                import zipfile
                with zipfile.ZipFile(fp, 'r') as zf:
                    mod_json = json.loads(zf.read('mod.json'))
                    sc_diff_data = None
                    for comp in mod_json.get('components', []):
                        if comp.get('target') == 'SC.GRP':
                            internal = comp.get('file', '')
                            if internal:
                                sc_diff_data = json.loads(zf.read(internal))
                                break

                if sc_diff_data:
                    for entry in sc_diff_data.get('modified', []):
                        idx = entry.get('index', -1)
                        data_b64 = entry.get('data_b64', '')
                        if 0 <= idx < len(sc_blocks) and data_b64:
                            sc_blocks[idx] = b64.b64decode(data_b64)

                self._data._sc_grp_pending = sc_blocks
                self._data._sc_grp_section_count = len(sc_blocks)
                imported_parts.append(f"SC.GRP ({len(sc_blocks)}区段, 待保存)")

        if not imported_parts:
            QMessageBox.warning(self, "导入失败",
                "无法导入任何数据。\n请确认参考目录中包含有效的游戏文件")
            return

        self._data._dirty = bool(has_sc)  # 有 SC.GRP 待保存则标记为 dirty
        self._last_mod_metadata = {
            "id": info.get("id", ""),
            "name": info.get("name", ""),
            "version": info.get("version", "1.0.0"),
            "author": info.get("author", ""),
            "description": info.get("description", ""),
            "load_order": info.get("load_order", 100),
        }

        self._apply_filter()
        self._vis_populate_scenes()

        # 自动跳转到导入的场景 (scene_scope)
        scene_scope = info.get('scene_scope', [])
        if scene_scope:
            target_sid = scene_scope[0]
        else:
            target_sid = self._canvas._vis_scene_id  # 保持原场景

        if target_sid is not None and target_sid >= 0:
            self._canvas._vis_scene_id = target_sid
            # 同步 combo 和 tree 的选中状态（阻止信号避免触发 _on_vis_combo_select）
            self._vis_scene_combo.blockSignals(True)
            for i in range(self._vis_scene_combo.count()):
                if self._vis_scene_combo.itemText(i).startswith(f"{target_sid}:"):
                    self._vis_scene_combo.setCurrentIndex(i)
                    break
            self._vis_scene_combo.blockSignals(False)
            self.scene_tree.blockSignals(True)
            for i in range(self.scene_tree.topLevelItemCount()):
                item = self.scene_tree.topLevelItem(i)
                if item and item.text(0) == str(target_sid):
                    self.scene_tree.setCurrentItem(item)
                    break
            self.scene_tree.blockSignals(False)

        self._vis_load_scene()
        # 以导入后的脚本状态作为新的删除检测基线, 避免把本次导入误判为脚本删除
        self._snapshot_script_baseline()
        self.status_var.setText(
            f"已导入 MOD: {info.get('name', '')} v{info.get('version', '')} | "
            f"{', '.join(imported_parts)}")
        QMessageBox.information(self, "导入成功",
            f"已导入 MOD: {info.get('name', '')}\n"
            f"版本: {info.get('version', '')}\n"
            f"作者: {info.get('author', '')}\n\n"
            f"导入内容: {', '.join(imported_parts)}\n\n"
            f"您现在可以继续编辑并重新导出。")
