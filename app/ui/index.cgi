#!/bin/bash

BASE_PATH="/var/apps/UEFIBootManager/target/www"
BACKUP_DIR="/vol1/@appshare/UEFIBootManager/backups"

URI_NO_QUERY="${REQUEST_URI%%\?*}"

REL_PATH="/"

case "$URI_NO_QUERY" in
    *index.cgi*)
        REL_PATH="${URI_NO_QUERY#*index.cgi}"
        ;;
esac

if [ -z "$REL_PATH" ] || [ "$REL_PATH" = "/" ]; then
    REL_PATH="/index.html"
fi

check_efibootmgr() {
    if ! command -v efibootmgr &> /dev/null; then
        echo "{\"success\":false,\"message\":\"efibootmgr未安装，请先安装efibootmgr\"}"
        return 1
    fi
    return 0
}

sanitize_input() {
    local val="$1"
    val=$(echo "$val" | sed 's/;/SEMICOLON/g; s/|/PIPE/g; s/`/BACKTICK/g; s/\$/DOLLAR/g')
    echo "$val"
}

ensure_backup_dir() {
    if [ ! -d "$BACKUP_DIR" ]; then
        mkdir_err=$(mkdir -p "$BACKUP_DIR" 2>&1)
        if [ ! -d "$BACKUP_DIR" ]; then
            return 1
        fi
    fi
    return 0
}

if [[ "$REL_PATH" == /api/* ]]; then
    echo "Content-Type: application/json; charset=utf-8"
    echo ""

    case "$REL_PATH" in
        /api/entries)
            if ! check_efibootmgr; then
                exit 0
            fi

            output=$(efibootmgr 2>&1)
            if [ $? -ne 0 ]; then
                error_msg=$(echo "$output" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"efibootmgr执行失败: $error_msg\"}"
                exit 0
            fi

            boot_current=$(echo "$output" | grep "^BootCurrent:" | awk '{print $2}')
            boot_next=$(echo "$output" | grep "^BootNext:" | awk '{print $2}')
            boot_order_str=$(echo "$output" | grep "^BootOrder:" | awk '{print $2}')

            entries_json="["
            first_entry=1
            while IFS= read -r line; do
                if [[ "$line" =~ ^Boot([0-9A-Fa-f]+)(\*?)[[:space:]]+(.*)$ ]]; then
                    boot_id="${BASH_REMATCH[1]}"
                    active_marker="${BASH_REMATCH[2]}"
                    boot_name="${BASH_REMATCH[3]}"

                    if [ -n "$active_marker" ]; then
                        is_active="true"
                    else
                        is_active="false"
                    fi

                    if [ $first_entry -eq 1 ]; then
                        first_entry=0
                    else
                        entries_json+=","
                    fi

                    boot_name_escaped=$(echo "$boot_name" | sed 's/\\/\\\\/g; s/"/\\"/g')
                    entries_json+="{\"id\":\"$boot_id\",\"name\":\"$boot_name_escaped\",\"active\":$is_active}"
                fi
            done <<< "$output"
            entries_json+="]"

            order_json="["
            if [ -n "$boot_order_str" ]; then
                first_order=1
                IFS=',' read -ra order_items <<< "$boot_order_str"
                for item in "${order_items[@]}"; do
                    if [ $first_order -eq 1 ]; then
                        first_order=0
                    else
                        order_json+=","
                    fi
                    order_json+="\"$item\""
                done
            fi
            order_json+="]"

            echo "{\"success\":true,\"data\":{\"boot_current\":\"$boot_current\",\"boot_next\":\"$boot_next\",\"boot_order\":$order_json,\"entries\":$entries_json}}"
            ;;

        /api/set_bootnext)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            boot_id=$(echo "$post_data" | sed -n 's/.*"boot_id"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$boot_id" ]; then
                echo '{"success":false,"message":"缺少boot_id参数"}'
                exit 0
            fi

            if ! echo "$boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的启动项编号"}'
                exit 0
            fi

            result=$(efibootmgr -n "$boot_id" 2>&1)
            if [ $? -eq 0 ]; then
                echo "{\"success\":true,\"message\":\"下次启动项已设置为 Boot$boot_id\"}"
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"设置失败: $error_msg\"}"
            fi
            ;;

        /api/clear_bootnext)
            if ! check_efibootmgr; then
                exit 0
            fi

            boot_next_val=$(efibootmgr 2>/dev/null | grep "^BootNext:" | awk '{print $2}')
            if [ -z "$boot_next_val" ]; then
                echo '{"success":true,"message":"下次启动项未设置，无需清除"}'
                exit 0
            fi

            result=$(efibootmgr -N 2>&1)
            if [ $? -eq 0 ]; then
                echo '{"success":true,"message":"下次启动项已清除"}'
            else
                if [ -d /sys/firmware/efi/efivars ]; then
                    rm -f /sys/firmware/efi/efivars/BootNext-* 2>/dev/null
                    new_val=$(efibootmgr 2>/dev/null | grep "^BootNext:" | awk '{print $2}')
                    if [ -z "$new_val" ]; then
                        echo '{"success":true,"message":"下次启动项已清除"}'
                        exit 0
                    fi
                fi
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"清除失败: $error_msg\"}"
            fi
            ;;

        /api/set_bootorder)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            order=$(echo "$post_data" | sed -n 's/.*"order"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$order" ]; then
                echo '{"success":false,"message":"缺少order参数"}'
                exit 0
            fi

            if ! echo "$order" | grep -qE '^[0-9A-Fa-f,]+$'; then
                echo '{"success":false,"message":"无效的启动顺序"}'
                exit 0
            fi

            result=$(efibootmgr -o "$order" 2>&1)
            if [ $? -eq 0 ]; then
                echo '{"success":true,"message":"启动顺序已更新"}'
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"设置失败: $error_msg\"}"
            fi
            ;;

        /api/disks)
            disks_json="["
            first_disk=1

            if command -v lsblk &> /dev/null; then
                while IFS= read -r line; do
                    if [ -z "$line" ]; then continue; fi

                    disk_name=$(echo "$line" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                    disk_size=$(echo "$line" | sed -n 's/.*SIZE="\([^"]*\)".*/\1/p')
                    disk_type=$(echo "$line" | sed -n 's/.*TYPE="\([^"]*\)".*/\1/p')
                    disk_pttype=$(echo "$line" | sed -n 's/.*PTTYPE="\([^"]*\)".*/\1/p')

                    if [ -z "$disk_name" ]; then continue; fi

                    disk_escaped=$(echo "$disk_name" | sed 's/"/\\"/g')

                    if [ $first_disk -eq 1 ]; then
                        first_disk=0
                    else
                        disks_json+=","
                    fi

                    parts_json="["
                    first_part=1
                    while IFS= read -r pline; do
                        if [ -z "$pline" ]; then continue; fi

                        part_name=$(echo "$pline" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                        if [ -z "$part_name" ] || [ "$part_name" = "$disk_name" ]; then continue; fi

                        part_size=$(echo "$pline" | sed -n 's/.*SIZE="\([^"]*\)".*/\1/p')
                        part_fstype=$(echo "$pline" | sed -n 's/.*FSTYPE="\([^"]*\)".*/\1/p')
                        part_mountpoint=$(echo "$pline" | sed -n 's/.*MOUNTPOINT="\([^"]*\)".*/\1/p')
                        part_number=$(echo "$part_name" | grep -oE '[0-9]+$')

                        part_name_escaped=$(echo "$part_name" | sed 's/"/\\"/g')
                        part_mountpoint_escaped=$(echo "$part_mountpoint" | sed 's/\\/\\\\/g; s/"/\\"/g')

                        if [ $first_part -eq 1 ]; then
                            first_part=0
                        else
                            parts_json+=","
                        fi

                        parts_json+="{\"name\":\"/dev/$part_name_escaped\",\"size\":\"$part_size\",\"fstype\":\"$part_fstype\",\"mountpoint\":\"$part_mountpoint_escaped\",\"number\":\"$part_number\"}"
                    done <<< "$(lsblk -Pn -o NAME,SIZE,FSTYPE,MOUNTPOINT "/dev/$disk_name" 2>/dev/null)"
                    parts_json+="]"

                    disks_json+="{\"name\":\"/dev/$disk_escaped\",\"size\":\"$disk_size\",\"type\":\"$disk_type\",\"pttype\":\"$disk_pttype\",\"partitions\":$parts_json}"
                done <<< "$(lsblk -Pdn -o NAME,SIZE,TYPE,PTTYPE 2>/dev/null | grep 'TYPE="disk"')"
            fi

            disks_json+="]"
            echo "{\"success\":true,\"data\":{\"disks\":$disks_json}}"
            ;;

        /api/entry_detail)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            boot_id=$(echo "$post_data" | sed -n 's/.*"boot_id"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$boot_id" ]; then
                echo '{"success":false,"message":"缺少boot_id参数"}'
                exit 0
            fi

            if ! echo "$boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的启动项编号"}'
                exit 0
            fi

            verbose_output=$(efibootmgr -v 2>&1)
            if [ $? -ne 0 ]; then
                error_msg=$(echo "$verbose_output" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"获取详细信息失败: $error_msg\"}"
                exit 0
            fi

            entry_line=$(echo "$verbose_output" | grep "^Boot${boot_id}")

            if [ -z "$entry_line" ]; then
                echo "{\"success\":false,\"message\":\"未找到启动项 Boot$boot_id\"}"
                exit 0
            fi

            if [[ "$entry_line" =~ ^Boot${boot_id}(\*?)[[:space:]]+(.*)$ ]]; then
                active_marker="${BASH_REMATCH[1]}"
                rest="${BASH_REMATCH[2]}"
            else
                echo "{\"success\":false,\"message\":\"无法解析启动项\"}"
                exit 0
            fi

            is_active="false"
            if [ -n "$active_marker" ]; then
                is_active="true"
            fi

            label=$(echo "$rest" | cut -f1 | sed 's/[[:space:]]*$//')
            device_path=$(echo "$rest" | cut -f2-)

            loader=$(echo "$device_path" | sed -n 's/.*File(\([^)]*\)).*/\1/p')
            partition=$(echo "$device_path" | sed -n 's/.*HD(\([0-9]*\),.*/\1/p')
            partuuid=$(echo "$device_path" | sed -n 's/.*HD([0-9]*,GPT,\([^,]*\),.*/\1/p')

            disk=""
            if [ -n "$partuuid" ]; then
                part_device=$(blkid -c /dev/null -t "PARTUUID=$partuuid" -o device 2>/dev/null | head -1)
                if [ -z "$part_device" ]; then
                    part_device=$(lsblk -rn -o NAME,PARTUUID 2>/dev/null | grep -i "$partuuid" | head -1 | awk '{print "/dev/"$1}')
                fi
                if [ -z "$part_device" ] && [ -n "$partition" ]; then
                    while IFS= read -r dline; do
                        dname=$(echo "$dline" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                        if [ -z "$dname" ]; then continue; fi
                        while IFS= read -r pline; do
                            pname=$(echo "$pline" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                            ppartuuid=$(echo "$pline" | sed -n 's/.*PARTUUID="\([^"]*\)".*/\1/p')
                            if [ "$ppartuuid" = "$partuuid" ]; then
                                part_device="/dev/$pname"
                                break 2
                            fi
                        done <<< "$(lsblk -Pn -o NAME,PARTUUID "/dev/$dname" 2>/dev/null)"
                    done <<< "$(lsblk -Pdn -o NAME 2>/dev/null | grep 'TYPE="disk"' || lsblk -Pdn -o NAME 2>/dev/null)"
                fi
                if [ -n "$part_device" ]; then
                    if [[ "$part_device" =~ ^/dev/(.+)p[0-9]+$ ]]; then
                        disk="/dev/${BASH_REMATCH[1]}"
                    elif [[ "$part_device" =~ ^/dev/(.+)([0-9]+)$ ]]; then
                        disk="/dev/${BASH_REMATCH[1]}"
                    fi
                fi
            fi

            label_escaped=$(echo "$label" | sed 's/\\/\\\\/g; s/"/\\"/g')
            loader_escaped=$(echo "$loader" | sed 's/\\/\\\\/g; s/"/\\"/g')
            device_path_escaped=$(echo "$device_path" | sed 's/\\/\\\\/g; s/"/\\"/g')

            echo "{\"success\":true,\"data\":{\"id\":\"$boot_id\",\"name\":\"$label_escaped\",\"active\":$is_active,\"loader\":\"$loader_escaped\",\"partition\":\"$partition\",\"disk\":\"$disk\",\"device_path\":\"$device_path_escaped\"}}"
            ;;

        /api/create_entry)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            label=$(echo "$post_data" | sed -n 's/.*"label"\s*:\s*"\([^"]*\)".*/\1/p')
            disk=$(echo "$post_data" | sed -n 's/.*"disk"\s*:\s*"\([^"]*\)".*/\1/p')
            partition=$(echo "$post_data" | sed -n 's/.*"partition"\s*:\s*"\([^"]*\)".*/\1/p')
            loader=$(echo "$post_data" | sed -n 's/.*"loader"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$label" ]; then
                echo '{"success":false,"message":"缺少启动项名称(label)"}'
                exit 0
            fi

            if [ -z "$disk" ]; then
                echo '{"success":false,"message":"缺少磁盘设备(disk)"}'
                exit 0
            fi

            if [ -z "$partition" ]; then
                echo '{"success":false,"message":"缺少分区编号(partition)"}'
                exit 0
            fi

            if [ -z "$loader" ]; then
                echo '{"success":false,"message":"缺少EFI加载器路径(loader)"}'
                exit 0
            fi

            if ! echo "$disk" | grep -qE '^/dev/[a-zA-Z0-9]+$'; then
                echo '{"success":false,"message":"无效的磁盘设备路径"}'
                exit 0
            fi

            if ! echo "$partition" | grep -qE '^[0-9]+$'; then
                echo '{"success":false,"message":"分区编号必须为数字"}'
                exit 0
            fi

            label=$(sanitize_input "$label")
            loader=$(sanitize_input "$loader")

            result=$(efibootmgr -c -d "$disk" -p "$partition" -L "$label" -l "$loader" 2>&1)
            if [ $? -eq 0 ]; then
                new_boot=$(echo "$result" | grep "^Boot" | tail -1 | sed 's/"/\\"/g')
                echo "{\"success\":true,\"message\":\"启动项创建成功\",\"detail\":\"$new_boot\"}"
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"创建失败: $error_msg\"}"
            fi
            ;;

        /api/update_entry)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            old_boot_id=$(echo "$post_data" | sed -n 's/.*"old_boot_id"\s*:\s*"\([^"]*\)".*/\1/p')
            new_label=$(echo "$post_data" | sed -n 's/.*"label"\s*:\s*"\([^"]*\)".*/\1/p')
            disk=$(echo "$post_data" | sed -n 's/.*"disk"\s*:\s*"\([^"]*\)".*/\1/p')
            partition=$(echo "$post_data" | sed -n 's/.*"partition"\s*:\s*"\([^"]*\)".*/\1/p')
            loader=$(echo "$post_data" | sed -n 's/.*"loader"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$old_boot_id" ]; then
                echo '{"success":false,"message":"缺少原始启动项编号"}'
                exit 0
            fi

            if ! echo "$old_boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的原始启动项编号"}'
                exit 0
            fi

            if [ -z "$new_label" ]; then
                echo '{"success":false,"message":"缺少启动项名称"}'
                exit 0
            fi

            if [ -z "$disk" ]; then
                echo '{"success":false,"message":"缺少磁盘设备"}'
                exit 0
            fi

            if [ -z "$partition" ]; then
                echo '{"success":false,"message":"缺少分区编号"}'
                exit 0
            fi

            if [ -z "$loader" ]; then
                echo '{"success":false,"message":"缺少EFI加载器路径"}'
                exit 0
            fi

            if ! echo "$disk" | grep -qE '^/dev/[a-zA-Z0-9]+$'; then
                echo '{"success":false,"message":"无效的磁盘设备路径"}'
                exit 0
            fi

            if ! echo "$partition" | grep -qE '^[0-9]+$'; then
                echo '{"success":false,"message":"分区编号必须为数字"}'
                exit 0
            fi

            new_label=$(sanitize_input "$new_label")
            loader=$(sanitize_input "$loader")

            current_order=$(efibootmgr | grep "^BootOrder:" | awk '{print $2}')

            result=$(efibootmgr -b "$old_boot_id" -B 2>&1)
            if [ $? -ne 0 ]; then
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"删除旧启动项失败: $error_msg\"}"
                exit 0
            fi

            order_after_delete=$(efibootmgr | grep "^BootOrder:" | awk '{print $2}')

            result=$(efibootmgr -c -d "$disk" -p "$partition" -L "$new_label" -l "$loader" 2>&1)
            if [ $? -ne 0 ]; then
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"创建新启动项失败: $error_msg\"}"
                exit 0
            fi

            order_after_create=$(efibootmgr | grep "^BootOrder:" | awk '{print $2}')

            new_id=""
            if [ -n "$order_after_create" ] && [ -n "$order_after_delete" ]; then
                IFS=',' read -ra old_ids <<< "$order_after_delete"
                IFS=',' read -ra new_ids <<< "$order_after_create"
                for nid in "${new_ids[@]}"; do
                    found=0
                    for oid in "${old_ids[@]}"; do
                        if [ "$nid" = "$oid" ]; then
                            found=1
                            break
                        fi
                    done
                    if [ $found -eq 0 ]; then
                        new_id="$nid"
                        break
                    fi
                done
            fi

            if [ -n "$current_order" ] && [ -n "$new_id" ]; then
                rebuilt_order=""
                first_o=1
                IFS=',' read -ra original_ids <<< "$current_order"
                for oid in "${original_ids[@]}"; do
                    if [ $first_o -eq 1 ]; then
                        first_o=0
                    else
                        rebuilt_order+=","
                    fi
                    if [ "$oid" = "$old_boot_id" ]; then
                        rebuilt_order+="$new_id"
                    else
                        rebuilt_order+="$oid"
                    fi
                done
                efibootmgr -o "$rebuilt_order" >/dev/null 2>&1
            fi

            echo "{\"success\":true,\"message\":\"启动项已更新，新编号为 Boot$new_id\",\"new_id\":\"$new_id\"}"
            ;;

        /api/delete_entry)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            boot_id=$(echo "$post_data" | sed -n 's/.*"boot_id"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$boot_id" ]; then
                echo '{"success":false,"message":"缺少boot_id参数"}'
                exit 0
            fi

            if ! echo "$boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的启动项编号"}'
                exit 0
            fi

            result=$(efibootmgr -b "$boot_id" -B 2>&1)
            if [ $? -eq 0 ]; then
                echo "{\"success\":true,\"message\":\"启动项 Boot$boot_id 已删除\"}"
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"删除失败: $error_msg\"}"
            fi
            ;;

        /api/activate_entry)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            boot_id=$(echo "$post_data" | sed -n 's/.*"boot_id"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$boot_id" ]; then
                echo '{"success":false,"message":"缺少boot_id参数"}'
                exit 0
            fi

            if ! echo "$boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的启动项编号"}'
                exit 0
            fi

            result=$(efibootmgr -b "$boot_id" -a 2>&1)
            if [ $? -eq 0 ]; then
                echo "{\"success\":true,\"message\":\"启动项 Boot$boot_id 已激活\"}"
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"激活失败: $error_msg\"}"
            fi
            ;;

        /api/deactivate_entry)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            boot_id=$(echo "$post_data" | sed -n 's/.*"boot_id"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$boot_id" ]; then
                echo '{"success":false,"message":"缺少boot_id参数"}'
                exit 0
            fi

            if ! echo "$boot_id" | grep -qE '^[0-9A-Fa-f]+$'; then
                echo '{"success":false,"message":"无效的启动项编号"}'
                exit 0
            fi

            result=$(efibootmgr -b "$boot_id" -A 2>&1)
            if [ $? -eq 0 ]; then
                echo "{\"success\":true,\"message\":\"启动项 Boot$boot_id 已禁用\"}"
            else
                error_msg=$(echo "$result" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"禁用失败: $error_msg\"}"
            fi
            ;;

        /api/backup)
            if ! check_efibootmgr; then
                exit 0
            fi

            if ! ensure_backup_dir; then
                echo "{\"success\":false,\"message\":\"无法创建备份目录: $BACKUP_DIR\"}"
                exit 0
            fi

            timestamp=$(date +%Y%m%d_%H%M%S)
            backup_file="$BACKUP_DIR/backup_${timestamp}.cfg"

            output=$(efibootmgr 2>&1)
            if [ $? -ne 0 ]; then
                error_msg=$(echo "$output" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"获取启动信息失败: $error_msg\"}"
                exit 0
            fi

            verbose_output=$(efibootmgr -v 2>&1)

            boot_current=$(echo "$output" | grep "^BootCurrent:" | awk '{print $2}')
            boot_next=$(echo "$output" | grep "^BootNext:" | awk '{print $2}')
            boot_order_str=$(echo "$output" | grep "^BootOrder:" | awk '{print $2}')

            backup_content=""
            backup_content+="timestamp=$timestamp"$'\n'
            backup_content+="boot_current=$boot_current"$'\n'
            backup_content+="boot_next=$boot_next"$'\n'
            backup_content+="boot_order=$boot_order_str"$'\n'

            while IFS= read -r line; do
                if [[ "$line" =~ ^Boot([0-9A-Fa-f]+)(\*?)[[:space:]]+(.*)$ ]]; then
                    bid="${BASH_REMATCH[1]}"
                    active_marker="${BASH_REMATCH[2]}"
                    rest="${BASH_REMATCH[3]}"

                    is_active="0"
                    if [ -n "$active_marker" ]; then
                        is_active="1"
                    fi

                    blabel=$(echo "$rest" | cut -f1 | sed 's/[[:space:]]*$//')
                    bdevice_path=$(echo "$rest" | cut -f2-)

                    bloader=$(echo "$bdevice_path" | sed -n 's/.*File(\([^)]*\)).*/\1/p')
                    bpartition=$(echo "$bdevice_path" | sed -n 's/.*HD(\([0-9]*\),.*/\1/p')
                    bpartuuid=$(echo "$bdevice_path" | sed -n 's/.*HD([0-9]*,GPT,\([^,]*\),.*/\1/p')

                    bdisk=""
                    if [ -n "$bpartuuid" ]; then
                        bpart_device=$(blkid -c /dev/null -t "PARTUUID=$bpartuuid" -o device 2>/dev/null | head -1)
                        if [ -z "$bpart_device" ]; then
                            bpart_device=$(lsblk -rn -o NAME,PARTUUID 2>/dev/null | grep -i "$bpartuuid" | head -1 | awk '{print "/dev/"$1}')
                        fi
                        if [ -z "$bpart_device" ] && [ -n "$bpartition" ]; then
                            while IFS= read -r dline; do
                                dname=$(echo "$dline" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                                if [ -z "$dname" ]; then continue; fi
                                while IFS= read -r pline; do
                                    pname=$(echo "$pline" | sed -n 's/.*NAME="\([^"]*\)".*/\1/p')
                                    ppartuuid=$(echo "$pline" | sed -n 's/.*PARTUUID="\([^"]*\)".*/\1/p')
                                    if [ "$ppartuuid" = "$bpartuuid" ]; then
                                        bpart_device="/dev/$pname"
                                        break 2
                                    fi
                                done <<< "$(lsblk -Pn -o NAME,PARTUUID "/dev/$dname" 2>/dev/null)"
                            done <<< "$(lsblk -Pdn -o NAME 2>/dev/null | grep 'TYPE="disk"' || lsblk -Pdn -o NAME 2>/dev/null)"
                        fi
                        if [ -n "$bpart_device" ]; then
                            if [[ "$bpart_device" =~ ^/dev/(.+)p[0-9]+$ ]]; then
                                bdisk="/dev/${BASH_REMATCH[1]}"
                            elif [[ "$bpart_device" =~ ^/dev/(.+)([0-9]+)$ ]]; then
                                bdisk="/dev/${BASH_REMATCH[1]}"
                            fi
                        fi
                    fi

                    backup_content+="[entry]"$'\n'
                    backup_content+="id=$bid"$'\n'
                    backup_content+="name=$blabel"$'\n'
                    backup_content+="active=$is_active"$'\n'
                    backup_content+="loader=$bloader"$'\n'
                    backup_content+="partition=$bpartition"$'\n'
                    backup_content+="disk=$bdisk"$'\n'
                fi
            done <<< "$verbose_output"

            write_err=$(echo "$backup_content" > "$backup_file" 2>&1)
            if [ $? -ne 0 ]; then
                err_msg=$(echo "$write_err" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"备份文件写入失败: $err_msg\"}"
                exit 0
            fi

            entry_count=0
            while IFS= read -r line; do
                if [[ "$line" =~ ^Boot[0-9A-Fa-f]+ ]]; then
                    entry_count=$((entry_count + 1))
                fi
            done <<< "$output"

            echo "{\"success\":true,\"message\":\"备份创建成功\",\"data\":{\"filename\":\"backup_${timestamp}.cfg\",\"timestamp\":\"$timestamp\",\"entry_count\":$entry_count}}"
            ;;

        /api/list_backups)
            if ! ensure_backup_dir; then
                echo "{\"success\":false,\"message\":\"无法访问备份目录: $BACKUP_DIR\"}"
                exit 0
            fi

            backups_json="["
            first_b=1

            for f in "$BACKUP_DIR"/backup_*.cfg "$BACKUP_DIR"/backup_*.json; do
                if [ ! -f "$f" ]; then continue; fi

                fname=$(basename "$f")
                ts=$(echo "$fname" | sed -n 's/backup_\([0-9_]*\)\.\(cfg\|json\)/\1/p')

                entry_count=0
                boot_order_val=""
                boot_next_val=""

                file_content=$(cat "$f" 2>/dev/null)
                if [ -n "$file_content" ]; then
                    entry_count=$(echo "$file_content" | grep -c '^\[entry\]')
                    boot_order_val=$(echo "$file_content" | grep '^boot_order=' | head -1 | cut -d= -f2-)
                    boot_next_val=$(echo "$file_content" | grep '^boot_next=' | head -1 | cut -d= -f2-)
                    if [ "$entry_count" -eq 0 ]; then
                        entry_count=$(echo "$file_content" | grep -o '"id"' | wc -l)
                    fi
                    if [ -z "$boot_order_val" ]; then
                        boot_order_val=$(echo "$file_content" | sed -n 's/.*"boot_order":\[\([^]]*\)\].*/\1/p' | tr -d '"' | head -1)
                    fi
                    if [ -z "$boot_next_val" ]; then
                        boot_next_val=$(echo "$file_content" | sed -n 's/.*"boot_next":"\([^"]*\)".*/\1/p')
                    fi
                fi

                fname_escaped=$(echo "$fname" | sed 's/"/\\"/g')

                if [ $first_b -eq 1 ]; then
                    first_b=0
                else
                    backups_json+=","
                fi

                backups_json+="{\"filename\":\"$fname_escaped\",\"timestamp\":\"$ts\",\"entry_count\":$entry_count,\"boot_order\":\"$boot_order_val\",\"boot_next\":\"$boot_next_val\"}"
            done

            backups_json+="]"
            echo "{\"success\":true,\"data\":{\"backups\":$backups_json}}"
            ;;

        /api/restore_backup)
            if ! check_efibootmgr; then
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            filename=$(echo "$post_data" | sed -n 's/.*"filename"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$filename" ]; then
                echo '{"success":false,"message":"缺少备份文件名"}'
                exit 0
            fi

            if echo "$filename" | grep -qE '\.\./|/'; then
                echo '{"success":false,"message":"无效的文件名"}'
                exit 0
            fi

            backup_file="$BACKUP_DIR/$filename"
            if [ ! -f "$backup_file" ]; then
                echo '{"success":false,"message":"备份文件不存在"}'
                exit 0
            fi

            file_content=$(cat "$backup_file" 2>&1)
            if [ -z "$file_content" ]; then
                echo '{"success":false,"message":"备份文件为空或无法读取"}'
                exit 0
            fi

            current_output=$(efibootmgr 2>&1)
            safety_ts=$(date +%Y%m%d_%H%M%S)
            safety_file="$BACKUP_DIR/auto_pre_restore_${safety_ts}.cfg"

            current_verbose=$(efibootmgr -v 2>&1)
            current_order=$(echo "$current_output" | grep "^BootOrder:" | awk '{print $2}')
            current_next=$(echo "$current_output" | grep "^BootNext:" | awk '{print $2}')

            safety_content=""
            safety_content+="timestamp=safety_${safety_ts}"$'\n'
            safety_content+="boot_next=$current_next"$'\n'
            safety_content+="boot_order=$current_order"$'\n'

            while IFS= read -r line; do
                if [[ "$line" =~ ^Boot([0-9A-Fa-f]+)(\*?)[[:space:]]+(.*)$ ]]; then
                    sbid="${BASH_REMATCH[1]}"
                    sactive="${BASH_REMATCH[2]}"
                    srest="${BASH_REMATCH[3]}"
                    slabel=$(echo "$srest" | cut -f1 | sed 's/[[:space:]]*$//')
                    s_is_active="0"
                    if [ -n "$sactive" ]; then s_is_active="1"; fi
                    safety_content+="[entry]"$'\n'
                    safety_content+="id=$sbid"$'\n'
                    safety_content+="name=$slabel"$'\n'
                    safety_content+="active=$s_is_active"$'\n'
                fi
            done <<< "$current_output"

            echo "$safety_content" > "$safety_file" 2>&1

            while IFS= read -r line; do
                if [[ "$line" =~ ^Boot([0-9A-Fa-f]+) ]]; then
                    del_id="${BASH_REMATCH[1]}"
                    efibootmgr -b "$del_id" -B >/dev/null 2>&1
                fi
            done <<< "$current_output"

            restored_count=0
            failed_count=0
            failed_entries=""
            id_map=""

            is_cfg_format=0
            if echo "$file_content" | grep -q '^\[entry\]'; then
                is_cfg_format=1
            fi

            if [ $is_cfg_format -eq 1 ]; then
                backup_order=$(echo "$file_content" | grep '^boot_order=' | head -1 | cut -d= -f2-)
                backup_next=$(echo "$file_content" | grep '^boot_next=' | head -1 | cut -d= -f2-)

                cur_eid=""
                cur_name=""
                cur_loader=""
                cur_disk=""
                cur_partition=""

                while IFS= read -r fline; do
                    if [[ "$fline" == "[entry]" ]]; then
                        if [ -n "$cur_eid" ]; then
                            edisk="$cur_disk"
                            epartition="$cur_partition"
                            elabel="$cur_name"
                            eloader="$cur_loader"
                            eid="$cur_eid"

                            if [ -z "$elabel" ] || [ -z "$edisk" ] || [ -z "$epartition" ] || [ -z "$eloader" ]; then
                                failed_count=$((failed_count + 1))
                                if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                                failed_entries+="Boot$eid($elabel)"
                            elif ! echo "$edisk" | grep -qE '^/dev/[a-zA-Z0-9]+$'; then
                                failed_count=$((failed_count + 1))
                                if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                                failed_entries+="Boot$eid($elabel)"
                            elif ! echo "$epartition" | grep -qE '^[0-9]+$'; then
                                failed_count=$((failed_count + 1))
                                if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                                failed_entries+="Boot$eid($elabel)"
                            else
                                elabel=$(sanitize_input "$elabel")
                                eloader=$(sanitize_input "$eloader")

                                order_before=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                                result=$(efibootmgr -c -d "$edisk" -p "$epartition" -L "$elabel" -l "$eloader" 2>&1)
                                if [ $? -eq 0 ]; then
                                    restored_count=$((restored_count + 1))
                                    order_after=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                                    new_id=""
                                    if [ -n "$order_before" ] && [ -n "$order_after" ]; then
                                        IFS=',' read -ra old_ids <<< "$order_before"
                                        IFS=',' read -ra new_ids <<< "$order_after"
                                        for nid in "${new_ids[@]}"; do
                                            found=0
                                            for oid in "${old_ids[@]}"; do
                                                if [ "$nid" = "$oid" ]; then found=1; break; fi
                                            done
                                            if [ $found -eq 0 ]; then new_id="$nid"; break; fi
                                        done
                                    fi
                                    if [ -n "$new_id" ] && [ -n "$eid" ]; then
                                        if [ -n "$id_map" ]; then id_map+=" "; fi
                                        id_map+="$eid:$new_id"
                                    fi
                                else
                                    failed_count=$((failed_count + 1))
                                    if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                                    failed_entries+="Boot$eid($elabel)"
                                fi
                            fi
                        fi
                        cur_eid=""
                        cur_name=""
                        cur_loader=""
                        cur_disk=""
                        cur_partition=""
                    else
                        fkey="${fline%%=*}"
                        fval="${fline#*=}"
                        case "$fkey" in
                            id) cur_eid="$fval" ;;
                            name) cur_name="$fval" ;;
                            loader) cur_loader="$fval" ;;
                            disk) cur_disk="$fval" ;;
                            partition) cur_partition="$fval" ;;
                        esac
                    fi
                done <<< "$file_content"

                if [ -n "$cur_eid" ]; then
                    edisk="$cur_disk"
                    epartition="$cur_partition"
                    elabel="$cur_name"
                    eloader="$cur_loader"
                    eid="$cur_eid"

                    if [ -z "$elabel" ] || [ -z "$edisk" ] || [ -z "$epartition" ] || [ -z "$eloader" ]; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                    elif ! echo "$edisk" | grep -qE '^/dev/[a-zA-Z0-9]+$'; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                    elif ! echo "$epartition" | grep -qE '^[0-9]+$'; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                    else
                        elabel=$(sanitize_input "$elabel")
                        eloader=$(sanitize_input "$eloader")

                        order_before=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                        result=$(efibootmgr -c -d "$edisk" -p "$epartition" -L "$elabel" -l "$eloader" 2>&1)
                        if [ $? -eq 0 ]; then
                            restored_count=$((restored_count + 1))
                            order_after=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                            new_id=""
                            if [ -n "$order_before" ] && [ -n "$order_after" ]; then
                                IFS=',' read -ra old_ids <<< "$order_before"
                                IFS=',' read -ra new_ids <<< "$order_after"
                                for nid in "${new_ids[@]}"; do
                                    found=0
                                    for oid in "${old_ids[@]}"; do
                                        if [ "$nid" = "$oid" ]; then found=1; break; fi
                                    done
                                    if [ $found -eq 0 ]; then new_id="$nid"; break; fi
                                done
                            fi
                            if [ -n "$new_id" ] && [ -n "$eid" ]; then
                                if [ -n "$id_map" ]; then id_map+=" "; fi
                                id_map+="$eid:$new_id"
                            fi
                        else
                            failed_count=$((failed_count + 1))
                            if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                            failed_entries+="Boot$eid($elabel)"
                        fi
                    fi
                fi
            else
                entries_str=$(echo "$file_content" | sed 's/.*"entries":\[//' | sed 's/\],"raw_verbose".*//' | sed 's/\],"boot_order".*//' | sed 's/\]}.*//')
                if [ -z "$entries_str" ]; then
                    echo '{"success":false,"message":"备份文件中未找到启动项数据"}'
                    exit 0
                fi

                backup_order=$(echo "$file_content" | sed -n 's/.*"boot_order":\[\([^]]*\)\].*/\1/p' | tr -d '"' | head -1)
                backup_next=$(echo "$file_content" | sed -n 's/.*"boot_next":"\([^"]*\)".*/\1/p')

                IFS='}' read -ra entry_blocks <<< "$entries_str"
                for eblock in "${entry_blocks[@]}"; do
                    eid=$(echo "$eblock" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
                    if [ -z "$eid" ]; then continue; fi

                    elabel=$(echo "$eblock" | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
                    eloader=$(echo "$eblock" | sed -n 's/.*"loader"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
                    edisk=$(echo "$eblock" | sed -n 's/.*"disk"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
                    epartition=$(echo "$eblock" | sed -n 's/.*"partition"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

                    if [ -z "$elabel" ] || [ -z "$edisk" ] || [ -z "$epartition" ] || [ -z "$eloader" ]; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                        continue
                    fi

                    if ! echo "$edisk" | grep -qE '^/dev/[a-zA-Z0-9]+$'; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                        continue
                    fi

                    if ! echo "$epartition" | grep -qE '^[0-9]+$'; then
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                        continue
                    fi

                    elabel=$(sanitize_input "$elabel")
                    eloader=$(sanitize_input "$eloader")

                    order_before=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                    result=$(efibootmgr -c -d "$edisk" -p "$epartition" -L "$elabel" -l "$eloader" 2>&1)
                    if [ $? -eq 0 ]; then
                        restored_count=$((restored_count + 1))
                        order_after=$(efibootmgr 2>/dev/null | grep "^BootOrder:" | awk '{print $2}')
                        new_id=""
                        if [ -n "$order_before" ] && [ -n "$order_after" ]; then
                            IFS=',' read -ra old_ids <<< "$order_before"
                            IFS=',' read -ra new_ids <<< "$order_after"
                            for nid in "${new_ids[@]}"; do
                                found=0
                                for oid in "${old_ids[@]}"; do
                                    if [ "$nid" = "$oid" ]; then found=1; break; fi
                                done
                                if [ $found -eq 0 ]; then new_id="$nid"; break; fi
                            done
                        fi
                        if [ -n "$new_id" ] && [ -n "$eid" ]; then
                            if [ -n "$id_map" ]; then id_map+=" "; fi
                            id_map+="$eid:$new_id"
                        fi
                    else
                        failed_count=$((failed_count + 1))
                        if [ -n "$failed_entries" ]; then failed_entries+=", "; fi
                        failed_entries+="Boot$eid($elabel)"
                    fi
                done
            fi

            if [ -n "$backup_order" ] && [ -n "$id_map" ]; then
                new_order=""
                first_no=1
                IFS=',' read -ra bitems <<< "$backup_order"
                for bo in "${bitems[@]}"; do
                    mapped_id="$bo"
                    for mapping in $id_map; do
                        old_i="${mapping%%:*}"
                        new_i="${mapping##*:}"
                        if [ "$bo" = "$old_i" ]; then
                            mapped_id="$new_i"
                            break
                        fi
                    done
                    if [ $first_no -eq 1 ]; then first_no=0; else new_order+=","; fi
                    new_order+="$mapped_id"
                done

                if [ -n "$new_order" ]; then
                    efibootmgr -o "$new_order" >/dev/null 2>&1
                fi
            fi

            if [ -n "$backup_next" ] && [ -n "$id_map" ]; then
                mapped_next="$backup_next"
                for mapping in $id_map; do
                    old_i="${mapping%%:*}"
                    new_i="${mapping##*:}"
                    if [ "$backup_next" = "$old_i" ]; then
                        mapped_next="$new_i"
                        break
                    fi
                done
                efibootmgr -n "$mapped_next" >/dev/null 2>&1
            fi

            msg="恢复完成: 成功 $restored_count 项"
            if [ $failed_count -gt 0 ]; then
                msg+=", 失败 $failed_count 项 ($failed_entries)"
            fi
            msg+=". 已自动创建恢复前安全备份: auto_pre_restore_${safety_ts}.cfg"

            echo "{\"success\":true,\"message\":\"$msg\",\"data\":{\"restored\":$restored_count,\"failed\":$failed_count,\"safety_backup\":\"auto_pre_restore_${safety_ts}.cfg\"}}"
            ;;

        /api/delete_backup)
            if ! ensure_backup_dir; then
                echo "{\"success\":false,\"message\":\"无法访问备份目录: $BACKUP_DIR\"}"
                exit 0
            fi

            if [ -z "$CONTENT_LENGTH" ] || [ "$CONTENT_LENGTH" -eq 0 ] 2>/dev/null; then
                echo '{"success":false,"message":"请求体为空"}'
                exit 0
            fi

            read -n "$CONTENT_LENGTH" post_data

            filename=$(echo "$post_data" | sed -n 's/.*"filename"\s*:\s*"\([^"]*\)".*/\1/p')

            if [ -z "$filename" ]; then
                echo '{"success":false,"message":"缺少备份文件名"}'
                exit 0
            fi

            if echo "$filename" | grep -qE '\.\./|/'; then
                echo '{"success":false,"message":"无效的文件名"}'
                exit 0
            fi

            backup_file="$BACKUP_DIR/$filename"
            if [ ! -f "$backup_file" ]; then
                echo '{"success":false,"message":"备份文件不存在"}'
                exit 0
            fi

            rm_err=$(rm -f "$backup_file" 2>&1)
            if [ $? -eq 0 ] && [ ! -f "$backup_file" ]; then
                echo "{\"success\":true,\"message\":\"备份 $filename 已删除\"}"
            else
                err_msg=$(echo "$rm_err" | head -1 | sed 's/"/\\"/g')
                echo "{\"success\":false,\"message\":\"删除备份文件失败: $err_msg\"}"
            fi
            ;;

        *)
            echo '{"success":false,"message":"未知的API接口"}'
            ;;
    esac
    exit 0
fi

TARGET_FILE="${BASE_PATH}${REL_PATH}"

if echo "$TARGET_FILE" | grep -q '\.\.'; then
    echo "Status: 400 Bad Request"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "Bad Request"
    exit 0
fi

if [ ! -f "$TARGET_FILE" ]; then
    echo "Status: 404 Not Found"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "404 Not Found: ${REL_PATH}"
    exit 0
fi

ext="${TARGET_FILE##*.}"
case "$ext" in
    html|htm)
        mime="text/html; charset=utf-8"
        ;;
    css)
        mime="text/css; charset=utf-8"
        ;;
    js)
        mime="application/javascript; charset=utf-8"
        ;;
    jpg|jpeg)
        mime="image/jpeg"
        ;;
    png)
        mime="image/png"
        ;;
    gif)
        mime="image/gif"
        ;;
    svg)
        mime="image/svg+xml"
        ;;
    txt|log)
        mime="text/plain; charset=utf-8"
        ;;
    *)
        mime="application/octet-stream"
        ;;
esac

echo "Content-Type: $mime"
echo ""
cat "$TARGET_FILE"
